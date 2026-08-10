# 16 — Features (รายละเอียดแต่ละฟีเจอร์)

> แต่ละฟีเจอร์อธิบาย: **เห็นยังไงฝั่ง user/staff/admin** + **flow ข้อมูล** + **config/DB ที่เกี่ยวข้อง** + **ไฟล์สำคัญ**
> คู่กับ [17-api-endpoints.md](17-api-endpoints.md) (endpoint) และ [02-database-schema.md](02-database-schema.md) (schema)

---

## 1. Auth + Onboarding

**เห็นยังไง:**
- คนเข้างาน: `/login` → กด Google → callback → ถ้ายังไม่ onboarding ไป `/onboarding` → กรอก ชื่อเล่น/คณะ/ภาค/รหัสนักศึกษา/ยอมรับ consent → เสร็จ

**Flow:**
1. `GET /auth/google/login` → ได้ authorize URL (PKCE + state ใน Redis 10 นาที)
2. Google redirect กลับ `/login?code=&state=`
3. `POST /auth/google/callback` → verify id_token (6 ชั้น: signature/JWKS, aud, iss, email_verified, domain allowlist, sub) → upsert user by `google_sub` → ออก JWT (15 นาที) + refresh cookie (30 วัน, httpOnly)
4. ถ้าอีเมลใน `ADMIN_EMAILS` → promote เป็น admin (ไม่ demote)
5. onboarding: `PATCH /me` ส่ง consent_photo → ตรวจ REQUIRED_FIELDS ก่อนเขียน → ถ้าครบ set `consent.tos=true` → **ออกบัตร QR อัตโนมัติ**

**สำคัญ:**
- `ALLOWED_EMAIL_DOMAINS` ว่าง = รับทุก domain (ทำให้คนที่หน้างานไม่ได้ล็อกอินเมลมหิดลเข้าได้ — ตัวตนมาจากข้อมูลที่กรอก ไม่ใช่ domain)
- `REQUIRED_FIELDS = (display_name, faculty, department, student_id)` — instagram_handle **ไม่** required (คนไม่มี IG จะติดที่ประตู)
- `needs_onboarding` คำนวณที่เดียว (`services/profile.py`) ใช้ใน login/refresh/me — กัน bounce
- refresh token: rotate ทุกครั้ง, ตรวจ reuse → revoke ทั้ง family

**ไฟล์:** `routers/auth.py`, `routers/me.py`, `services/google_oauth.py`, `services/profile.py`, `services/tickets.py`
**หน้า:** `/login`, `/onboarding`
**Config:** `GOOGLE_*`, `ALLOWED_EMAIL_DOMAINS`, `ADMIN_EMAILS`, `JWT_SECRET`, `TOKEN_VERSION`

---

## 2. QR Check-in (เช็คอินหน้างาน)

**เห็นยังไง:**
- คนเข้างาน: `/ticket` โชว์ QR 1 ใบ (ใช้ได้ทั้ง 3 วัน) + rotating code + badge วันที่เช็คแล้ว
- Staff: `/scan` โหมด `checkin` → เลือกวัน 1/2/3 → สแกน (กล้อง/มือ) → เขียว OK / เหลือง DUPLICATE / แดง error
- Admin/Staff: `/admin/attendees` หรือ `/staff/attendees` → ค้นชื่อ → กดเช็คชื่อมือ (admin undo ได้, staff ไม่ได้)

**Flow สแกน (`POST /checkin`):**
1. HMAC verify payload offline (`verify_qr_payload`) — ไม่แตะ DB, ปฏิเสธของปลอมทันที
2. หา ticket by `ticket_code` → reject ถ้า revoked
3. ถ้า `STRICT_QR_MODE` → ตรวจ TOTP rotating code
4. **Dedupe รายวัน**: Redis `SET NX ci:{ticket_id}:d{day}` TTL 4 วัน (ด่านจริง) + Mongo `$addToSet checked_in_days` (ด่านสำรอง ถ้า Redis flush)
5. **ให้ coin รายวัน**: `coins.award(idempotency_key=f"checkin:{code}:d{day}")` → มา 3 วันได้ 3×`CHECKIN_COINS`
6. stats Redis + audit log (`Col.checkins()`)
7. **push notify** (ดูฟีเจอร์ SSE/AT)

**สำคัญ:**
- 1 ticket/user ทั้งงาน (unique index `uq_user` บน `tickets.user_id`)
- `status` อยู่ที่ `"issued"` เสมอ (ไม่ flip เป็น checked_in เพราะใช้ข้ามวัน) — เก็บวันที่เช็คใน `checked_in_days: [1,2,3]`
- offline queue ใน `/scan` (localStorage) → `POST /checkin/batch` ตอนกลับมาออนไลน์ (กระบวลผลทีละตัว ไม่ล้มทั้ง batch)
- admin undo: `POST /admin/checkin/undo` — ล้าง Mongo + Redis dedupe (ไม่คืน coin)

**ไฟล์:** `routers/checkin.py`, `routers/admin.py`, `routers/staff.py`, `services/tickets.py`, `services/attendance.py`, `core/security.py`
**หน้า:** `/ticket`, `/scan`, `/admin/attendees`, `/staff/attendees`
**Config:** `QR_SIGNING_KEY`, `TOTP_KEY`, `STRICT_QR_MODE`, `CHECKIN_COINS=10`

---

## 3. SSE Push + Attendance (AT) Prompt

**เห็นยังไง:**
- ตอนคนเข้างานถูกสแกน → modal เด้งที่มือถือ "เช็คอินสำเร็จ +N coin วัน X — กรุณากรอกฟอร์ม Attendance" + ปุ่มไป Google Form
- ถ้าตอนสแกนมือถือปิดอยู่ → reconnect แล้ว replay / หรือ login ใหม่แล้วเด้ง (อ่าน Mongo)

**Flow:**
1. มือถือเปิด `EventSource('/me/stream?token=...')` (token ใน query — EventSource ใส่ header ไม่ได้)
2. server: `retry: 5000` + replay `notify:last:{uid}` (TTL 1h) + subscribe ผ่าน **singleton `notify_manager`** (1 Redis connection สำหรับทุก user — กัน pool exhaustion)
3. staff สแกน → `checkin_core` publish `checkin_ok` ไป channel กลาง `notify:checkin` + set `notify:last:{uid}`
4. `notify_manager` route ไป queue ของ user นั้น → SSE ส่ง `event: checkin_ok`
5. frontend `useCheckinNotify` → `useNotifyStore.show()` → `<CheckinModal/>` เด้ง
6. ปิด modal → `POST /me/at-prompt/dismiss` set `at:dismissed:{uid}` TTL 1h (suppress re-show ทาง login path)
7. login/app-open → `GET /me/at-prompt` อ่าน ticket Mongo → ถ้าเช็คล่าสุดภายใน 6h → re-show

**สำคัญ:**
- `<CheckinModal/>` ซ่อนใน `/scan`, `/admin`, `/display` (ไม่บล็อก staff/จอ)
- `retry: 5000` + exponential backoff (5s→30s) กัน reconnect storm
- ไม่ติดตามว่ากรอกฟอร์มหรือไม่ — แค่แจ้ง; `ATTENDANCE_FORM_URL` ว่าง = ซ่อนปุ่ม
- SSE ถูก GZip ข้ามไป (`GZipExceptSSEMiddleware`) ไม่งั้น chunk ถูก buffer push ไม่สด

**ไฟล์:** `routers/me.py` (`/me/stream`, `/me/at-prompt`, `/me/at-prompt/dismiss`), `routers/checkin.py` (publish), `realtime/notify_manager.py`, `core/gzip.py`
**หน้า:** modal global (`components/CheckinModal.tsx`, `lib/notify.ts`, `lib/providers.tsx`)
**Config:** `ATTENDANCE_FORM_URL`

---

## 4. Quests (กิจกรรมบูธ)

**เห็นยังไง:**
- คนเข้างาน: `/quests` เห็นรายการกิจกรรม + coin ที่ได้ + ความคืบหน้า (X/N) + ปุ่มเปิด `/ticket` ให้ staff สแกน
- Admin: `/admin/quests` CRUD quest (key/title/description/coins/max_per_user/sort_order/status)
- Staff: `/scan` โหมด `coins` สแกน QR คนเข้างานที่บูธ → จ่าย coin

**Flow รับ coin บูธ (`POST /quests/claim` หรือ `POST /staff/coins/grant`):**
- **Quest claim**: staff สแกน QR → ระบุ `quest_key` → ให้ coin ตาม quest → กันซ้ำด้วย **unique index `(quest_key, user_id, seq)`**
- **Staff grant (ไม่ผูก quest)**: staff ระบุจำนวนเอง → ผ่าน quota 4 ชั้น → ให้ coin ทันที (บูธเก็บเงินเอง, ระบบแค่จ่ายรางวัล)

**สำคัญ — staff grant quota (กันทุจริต):**
4 ชั้นใน `services/grant_limits.py` (Redis INCRBY, day-key ปฏิทินไทย):
| ชั้น | Config | ความหมาย |
|---|---|---|
| per-scan | `STAFF_GRANT_MAX_PER_SCAN=200` | สแกน 1 ครั้งจ่ายสูงสุด |
| pair-daily | `STAFF_GRANT_PER_USER_DAILY=300` | staff คนนึง → user คนนึง ต่อวัน |
| receive-daily | `USER_GRANT_RECEIVE_DAILY=1500` | user คนนึง รับจากทุกบูธ ต่อวัน |
| staff-daily | `STAFF_GRANT_DAILY_BUDGET=20000` | staff คนนึง จ่ายรวม ต่อวัน |

- 20s cooldown ต่อ (device, ticket)
- admin reset ได้แค่ budget รายวันของ staff (ไม่แตะ pair/receive — กันทุจริต)
- `GET /admin/grants/summary` ส่ง staff↔receiver pair ranking (สัญญาณทุจริต — "hot" pair = ≥60% ของอันดับ 1 + ≥3 ครั้ง)

**ไฟล์:** `routers/quests.py`, `routers/staff.py`, `routers/admin.py`, `services/grant_limits.py`
**หน้า:** `/quests`, `/admin/quests`, `/admin/grants`, `/scan` (โหมด coins)
**DB:** `quests`, `quest_claims` (unique `(quest_key, user_id, seq)`)
**Config:** `STAFF_GRANT_*`, `features.quests`

---

## 5. Voting (โหวตศิลปิน)

**เห็นยังไง:**
- คนเข้างาน: `/vote` เห็นรอบที่เปิด → modal ยืนยันก่อนโหวต → โหวตแล้วล็อกทั้งรอบ → ดูผลเป็น bar
- Admin: `/admin/rounds` เปิด/ปิด (freeze ผล)/ประกาศผล (เปิดให้ user เห็น)
- จอ display: `/display/vote` กราฟสด poll 1 วิ

**Flow (`POST /votes`):**
- ทำงานด้วย **Lua script** ใน Redis 1 round-trip — **ไม่แตะ MongoDB** ใน request path
- dedupe key `vote:{round}:{uid}` TTL 5 วัน + tally hash + ZSET leaderboard
- ถ้า `REQUIRE_CHECKIN_TO_VOTE=true` → ตรวจว่าเช็คอินแล้ว
- worker drain `stream:votes` → Mongo เบื้องหลัง (Mongo ล่มก็โหวตได้)

**สำคัญ:**
- 1 คน 1 โหวตต่อรอบ (unique index `uq_round_user` เป็นด่านสำรอง)
- ผลซ่อนถ้า `results_public=false` (admin ปิดจนถึงเวลาประกาศ)
- ปิดรอบ → freeze tally จาก Redis → Mongo `final_tally` (ผลทางการ)

**ไฟล์:** `routers/votes.py`, `lua/vote.lua`, `workers/runner.py`
**หน้า:** `/vote`, `/admin/rounds`, `/display/vote`
**DB:** `vote_rounds`, `votes`, `vote_tallies`
**Config:** `REQUIRE_CHECKIN_TO_VOTE`

---

## 6. IG Wall (ส่งโพสต์ขึ้นจอใหญ่)

**เห็นยังไง:**
- คนเข้างาน: `/ig` เลือกรูป + IG handle + แคปชัน → จ่าย `WALL_COST=20` coin → รอ admin อนุมัติ
- Admin: `/admin/ig` คิว pending → ดูภาพ/แคปชัน/flag → อนุมัติ (ขึ้นจอ) / ปฏิเสธ (คืน coin)
- จอ display: `/display/ig` ทีละโพสต์ 45s + ช่องว่าง 3s

**Flow:**
- `POST /ig/submissions` → `coins.spend(20)` (atomic) → insert doc status=pending + base64 image
- admin approve → status=approved (ไม่ให้ coin เพิ่ม — การอนุมัติ = ส่งมอบช่องที่ซื้อ)
- admin reject → refund `IG_WALL_COST` (idempotent by shortcode)
- จอ display: `GET /live/ig-wall` ดึง approved ที่ยังไม่ `wall_shown_at` → โชว์ → `POST /live/ig-wall/{id}/shown` (gated `DISPLAY_TOKEN`) บอกว่าโชว์แล้ว (ไม่ใช้ timer backend เพราะถ้าจอปิด คิวจะไม่รั่ว)

**สำคัญ:**
- IG wall = "ซื้อช่อง" ไม่ใช่ "รางวัล" (เคยเป็นรางวัล 50 coin + จ่าย 20 = exploit)
- client downscale 1440px JPEG q0.82 ก่อนอัป (ลดขนาด)
- `IG_APPROVED_COINS` ถูกลบแล้ว
- ไม่ส่ง base64 กลับใน list endpoint (เฉพาะ `GET /ig/image/{id}`)

**ไฟล์:** `routers/ig.py`, `routers/admin.py`, `routers/live.py`
**หน้า:** `/ig`, `/admin/ig`, `/display/ig`
**Config:** `WALL_COST=20` (ใน `ig.py`), `DISPLAY_TOKEN`

---

## 7. Wheel (ตู้สล็อต provably-fair)

**เห็นยังไง:**
- คนเข้างาน: `/wheel` ตู้สล็อต 3 รีล + คันโยก → กดหมุน (จ่าย `cost_coins`) → animation → ผล → รับรางวัล (coin/ของ)

**Flow (`POST /wheel/{key}/spin`):**
1. `coins.spend(cost)` (atomic)
2. compute: `index = HMAC_SHA256(server_seed, client_seed:nonce)[:8] % sum(weights)`
3. atomic stock decrement (ถ้าของมีจำกัด)
4. record spin + `coins.award(prize)` (ถ้าถูก)
5. duplicate nonce → refund (unique index `uq_user_nonce`)

**สำคัญ — provably-fair:**
- `commit_hash = sha256(server_seed)` ประกาศก่อนงาน (ตอน wheel เปิด)
- หลังงาน wheel ปิด → `GET /wheel/{key}/verify` เปิดเผย `server_seed` → user ตรวจย้อนได้
- `nonce` = ลำดับ spin ของ user (ไม่ใช่สุ่ม) กัน unique index collision
- **ไม่มี** `POST /admin/wheel/{key}/trigger` แล้ว (เคยมี สำหรับหมุนบนเวที — ตัดออก, wheel เป็น player-only)

**ไฟล์:** `routers/wheel.py`, `services/wheel_engine.py`
**หน้า:** `/wheel`
**DB:** `wheel_configs`, `wheel_spins`
**Config:** `WHEEL_SERVER_SEED`

---

## 8. Coins (ระบบเหรียญ)

**เห็นยังไัย:**
- คนเข้างาน: `/points` ดูยอด + ledger เต็ม (reason เป็นภาษาไทย)
- Admin: `/admin/users` ปรับ coin มือ (ต้องใส่เหตุผล)

**โมเดล:**
- `users.coins_balance` = **cache** (เร็ว แต่ไม่ใช่ source of truth)
- `coin_transactions` = **append-only ledger** (source of truth)
- `services/coins.py`: `spend()` (atomic `$inc` มีเงื่อน `balance >= amount`), `award()` (insert ledger ก่อน → `$inc`)
- worker รัน `reconcile_all()` ทุก 5 นาที → แก้ drift → export `coins_drift` gauge

**Reason codes** (label ไทยใน `/points`):
`checkin` · `instagram_approved` (legacy) · `wheel_cost` · `wheel_prize` · `ig_wall` · `admin_adjust` · `staff_grant` · `quest` · `referral` · `topup` (legacy)

**สำคัญ:**
- idempotent ทุก transaction (unique `idempotency_key`)
- negative amount ได้ (admin adjust)
- `GET /me/export` PDPA export (profile + ledger + votes)

**ไฟล์:** `services/coins.py`, `routers/me.py`, `routers/admin.py`
**หน้า:** `/points`, `/admin/users`
**DB:** `coin_transactions`, `users.coins_balance`

---

## 9. Exports (CSV)

**เห็นยังไง:** Admin `/admin/export` กดดาวน์โหลด CSV

**Endpoints (`routers/exports.py`, admin-only):**
- `GET /admin/export/checkins.csv` — ทุกการสแกน (รวม reject) + join user/staff, filter `event_day`/`result`
- `GET /admin/export/attendees.csv` — 1 แถว/คน + mark วันที่เช็ค + ยอด coin
- `GET /admin/export/coins.csv` — ledger เต็ม + `balance_after` + reason ไทย + actor, filter `reason`

**สำคัญ:**
- streaming (ไม่โหลดทั้งไฟล์ขึ้น RAM)
- UTF-8 BOM + `\r\n` (Excel)
- เวลาแปลง +07:00 ตายตัว (ไม่ใช้ ZoneInfo — กัน tzdata runtime crash)
- batch-join user (PAGE=1000) ไม่ใช่ per-row

**ไฟล์:** `routers/exports.py`, `lib/timeutil.py`
**หน้า:** `/admin/export`

---

## 10. Audit Log

**เห็นยังไง:** Admin `/admin/audit` ดูประวัติทุก action — infinite scroll, กรองตามกลุ่ม action, before/after diff

**สำคัญ:**
- ทุก admin/staff action เขียน audit (ผ่าน `services/audit.py`) — actor, action, target, before/after, ip_hash (PDPA)
- action ที่ sensitive (`coins.adjust`, `checkin.undo`, `quest.delete`, `config.patch`) highlight
- infinite scroll ใช้ cursor (`next_cursor`) — แก้ bug เดิมที่ตัดที่ 50 แถว

**ไฟล์:** `services/audit.py`, `routers/admin.py` (`/admin/audit-logs*`)
**หน้า:** `/admin/audit`
**DB:** `audit_logs`

---

## 11. Config / Feature Flags (ฉุกเฉิน)

**เห็นยังไัย:** Admin `/admin/config` toggle ทันที (มีผลใน 5 วิ ไม่ต้อง deploy)

**Toggle ได้:**
- `maintenance_mode` (ปิดทุกอย่าง → 503)
- `read_only_mode` (อ่านได้ เขียนไม่ได้ — หยุดเลือด)
- `features`: `voting`, `wheel`, `ig_submission`, `checkin`, `quests` (quests = บูธจ่าย coin)
- `announcement`: ข้อความประกาศ (โชว์ banner บน home)

**สำคัญ:**
- config cache ใน Redis 5 วิ → admin patch → ล้าง cache → 5 วิมีผล
- `require_feature(name)` dependency ใช้ gate endpoint
- `require_writable` ใช้ gate write endpoint ตอน read-only

**ไฟล์:** `routers/admin.py` (`/admin/config`), `core/deps.py`
**หน้า:** `/admin/config`
**DB:** `system_config`

---

## 12. Realtime Infrastructure

**2 ระบบแยกกัน:**

### A. Display WebSocket (`ws_main.py` — process แยก)
- endpoint `GET /v1/live/ws?token=DISPLAY_TOKEN` (token เดียวกันทุกจอ, **ห้าม** ให้มือถือใช้)
- singleton `realtime/manager.py` subscribe `live:events` 1 channel → fanout ทุกจอ
- ส่ง snapshot ทุก 1 วิ (broadcaster worker) + event wheel/vote

### B. User SSE (`me.py /me/stream` — ใน REST process)
- `notify_manager` singleton subscribe `notify:checkin` 1 channel → route ไป queue ราย user
- ใช้ Redis connection เดียว รองรับ 500+ มือถือเปิดพร้อมกัน

### Snapshot polling (มือถือทั่วไป)
- `GET /live/snapshot` อ่าน Redis `live:snapshot` (สร้างโดย broadcaster) — pure GET + ETag + cache 1 วิ → รับ 667 rps ได้
- มือถือ poll ทุก 3 วิ (หยุดตอน tab ซ่อน)

**สำคัญ:** มือถือใช้ snapshot polling ไม่ใช่ WS (2,000 WS = reconnect storm ระบบตาย) ยกเว้น SSE สำหรับ check-in push ที่ใช้จริง

**ไฟล์:** `ws_main.py`, `realtime/manager.py`, `realtime/notify_manager.py`, `workers/broadcaster.py`, `routers/live.py`, `routers/me.py`

---

## 13. Avatars + Profile

**เห็นยังไง:**
- `/profile` ดู/แก้โปรไฟล์ + อัป avatar + **ดาวน์โหลดข้อมูลของฉัน (PDPA)**
- avatar เก็บเป็น base64 ใน Mongo (`avatar_data`) หรือ Google URL

**Flow:**
- `POST /me/avatar` → validate magic bytes (jpeg/png/webp) + ≤512KB → เก็บ base64 + set `avatar_url` เป็น `/v1/avatars/{id}`
- `GET /avatars/{user_id}` public — ส่ง binary จาก Mongo หรือ 302 ไป Google URL
- login ใหม่: ถ้ามี avatar ที่ upload เอง → ไม่ให้ Google URL เขียนทับ

**ไฟล์:** `routers/me.py`, `routers/avatars.py`, `components/ProfileCard.tsx`
**หน้า:** `/profile`, `/onboarding`

---

## ภาพรวมระบบ (cheat sheet)

```
มือถือคนเข้างาน (login @mahidol หรือ @อื่น)
  ├─ /ticket     QR 1 ใบ 3 วัน ──สแกน──→ staff /scan
  ├─ /quests     กิจกรรมบูธ ──สแกน──→ staff /scan (coins)
  ├─ /vote       โหวต ──→ Redis Lua (ไม่แตะ Mongo)
  ├─ /ig         ส่งโพสต์ (จ่าย 20) ──→ admin /admin/ig อนุมัติ ──→ /display/ig
  ├─ /wheel      ตู้สล็อต (provably-fair)
  ├─ /points     ledger
  └─ /me/stream  SSE ←── push ตอนถูกสแกน (modal Attendance)

Staff (role staff/admin)
  ├─ /scan       สแกนเช็คอิน + สแกนจ่าย coin (quota 4 ชั้น)
  └─ /staff/attendees  เช็คชื่อมือ (ไม่มี undo)

Admin (role admin)
  ├─ /admin/*    ดังบอร์ด/ผู้ใช้/quest/รอบโหวต/IG/grant/export/audit/config
  └─ /admin/attendees  เช็คชื่อมือ (undo ได้)

จอ display (DISPLAY_TOKEN)
  ├─ /display/ig     IG wall 45s/โพสต์
  └─ /display/vote   ผลโหวตสด
```
