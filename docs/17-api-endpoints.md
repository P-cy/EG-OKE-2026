# 17 — API Endpoints (ทั้งหมด)

> รายการ endpoint ครบทั้งหมด แยกตามกลุ่ม + auth + body/response แบบกระชับ
> คู่กับ [16-features.md](16-features.md) (flow เต็ม) — ที่นี่คือ reference
> OpenAPI interactive อยู่ที่ `GET /docs` (เฉพาะตอน `ENABLE_DOCS=true`)

## Conventions

| หัวข้อ | กติกา |
|---|---|
| Base | `/v1` (ยกเว้น health/ops) |
| Auth | `Authorization: Bearer <jwt>` (15 นาที) — ยกเว้น SSE ที่ใช้ `?token=` |
| Refresh | httpOnly cookie `rt` (30 วัน, rotate ทุกครั้ง) |
| Idempotency | `Idempotency-Key: <uuid>` บังคับทุก POST/PATCH/PUT/DELETE เปลี่ยน state |
| Pagination | cursor: `?limit=50&cursor=<opaque>` (ห้าม skip) |
| เวลา | ISO 8601 UTC (`2026-08-05T12:00:00Z`) |
| Error | `{error:{code,message,message_en,details,request_id}}` |

**Auth legend:** 🔓 public · 👤 user · 🛡️ staff (`staff`/`admin`) · 👑 admin · 🖥️ display token

---

## ops (ไม่มี prefix)

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| GET | `/healthz` | 🔓 | liveness — 200 เสมอถ้า process มีชีวิต |
| GET | `/readyz` | 🔓 | readiness — 503 ถ้า Redis down (Mongo down = degraded ไม่ใช่ 503) |
| GET | `/version` | 🔓 | `APP_VERSION`, `GIT_SHA`, `BUILD_TIME`, `ENV` |
| GET | `/metrics` | 🔓 (IP allowlist `METRICS_ALLOWED_IPS`) | Prometheus scrape |

---

## auth — `/auth`

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| GET | `/auth/google/login` | 🔓 | เริ่ม OAuth + PKCE → `{authorize_url, state}` (state ใน Redis 10 นาที) |
| POST | `/auth/google/callback` | 🔓 | `{code, state}` → `{access_token, expires_in, user}` + Set-Cookie `rt` |
| POST | `/auth/refresh` | 🍪 cookie | rotate refresh → `{access_token, user}` (ตรวจ reuse → revoke family) |
| POST | `/auth/logout` | 👤 | denylist jti + revoke refresh family |

---

## me — `/me`

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| GET | `/me` | 👤 | profile + coin rank |
| PATCH | `/me` | 👤 | update profile — ตอน set `consent_photo` ตรวจ REQUIRED_FIELDS ก่อน + ออกบัตร |
| POST | `/me/avatar` | 👤 | `{image_data, mime}` base64 (validate magic bytes, ≤512KB) |
| GET | `/me/points` | 👤 | ledger ของตัวเอง (cursor pagination) `{balance, items, next_cursor}` |
| GET | `/me/tickets` | 👤 | `[QROut]` — บัตร + QR payload + rotating code |
| GET | `/me/submissions` | 👤 | IG submissions ของตัวเอง (ไม่มี base64) |
| GET | `/me/export` | 👤 | PDPA export (profile + ledger + votes) |
| GET | `/me/at-prompt` | 👤 | `{show, event_day, coins_awarded, form_url, checked_in_at}` — โชว์ modal AT ไหม |
| POST | `/me/at-prompt/dismiss` | 👤 | suppress re-show 1 ชม. → `{ok}` |
| GET | `/me/stream` | 👤 `?token=` | **SSE** push `checkin_ok` — `retry: 5000` + replay + `: ping` ทุก 25s |

---

## checkin — `/checkin`

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| POST | `/checkin` | 🛡️ | `{payload, event_day(1-3), gate?, device_id, scanned_at?, rotating_code?}` → `CheckinOut{result, event_day, user, coins_awarded, ...}` — dedupe รายวัน + ให้ coin รายวัน |
| POST | `/checkin/batch` | 🛡️ | `{items:[CheckinIn]}` (≤100) — offline queue replay, ประมวลผลทีละตัว |

`CheckinOut.result`: `ok` · `duplicate` · `invalid_sig` · `revoked` · `wrong_day` · `expired` · `rotating_code_mismatch` · `not_found`

---

## quests — `/quests`

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| GET | `/quests` | 👤 | `[QuestPublic]` quest ที่เปิด + claim count ของตัวเอง |
| POST | `/quests/claim` | 🛡️ | `{quest_key, payload/ticket_code/student_id, seq}` → `QuestClaimOut` — ให้ coin, กันซ้ำด้วย unique index `(quest_key, user_id, seq)` |

---

## votes — `/votes` + `/vote-rounds`

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| GET | `/vote-rounds` | 👤 (optional) | `[VoteRoundPublic]` รอบที่เปิด + my_vote |
| GET | `/vote-rounds/{round_key}/results` | 👤 (optional) | tally (ซ่อนถ้าไม่ `results_public` และไม่ใช่ admin) |
| POST | `/votes` | 👤 | `{round_key, artist_id}` → 202 `VoteOut` — atomic Lua Redis-only, ไม่แตะ Mongo |

---

## instagram — `/ig`

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| GET | `/ig/config` | 🔓 | `{cost_coins, image_max_bytes, caption_max, handle_pattern}` |
| POST | `/ig/submissions` | 👤 | `{image_data, instagram_handle, caption?}` → 201 — `coins.spend(20)` ก่อน insert |
| GET | `/ig/image/{submission_id}` | 🔓 | ภาพ approved submission, `Cache-Control: immutable` |

---

## wheel — `/wheel`

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| GET | `/wheel/{wheel_key}` | 👤 | config + segments (ซ่อน weight) + `commit_hash` + my spin count |
| POST | `/wheel/{wheel_key}/spin` | 👤 | `{client_seed, nonce}` → `SpinOut` — spend → HMAC compute → stock decrement → award |
| GET | `/wheel/{wheel_key}/verify` | 🔓 | เปิดเผย `server_seed` (เฉพาะ wheel `status=closed`) สำหรับตรวจ provably-fair |

---

## live — `/live` (public, cached)

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| GET | `/live/snapshot` | 🔓 | snapshot ทั้งงานจาก Redis (ETag + cache 1s) — pure GET, ไม่คำนวณ |
| GET | `/live/checkin-stats` | 🔓 | `{today, rate_per_min, gates, recent}` |
| GET | `/live/ig-wall` | 🔓 | `{items, as_of}` approved posts ที่ยังไม่ shown (มี image URL ไม่ใช่ base64) |
| POST | `/live/ig-wall/{submission_id}/shown` | 🖥️ | บอกว่าจอโชว์โพสต์นี้แล้ว (`?token=DISPLAY_TOKEN`) |

> `GET /live/leaderboard` ถูกลบแล้ว — coin leaderboard เป็น private (ดูได้ใน `/me`)

---

## avatars — `/avatars`

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| GET | `/avatars/{user_id}` | 🔓 | binary จาก Mongo หรือ 302 ไป Google URL, `Cache-Control: immutable` |

---

## staff — `/staff` (🛡️ staff/admin)

| Method | Path | Auth | หน้าที่ |
|---|---|---|---|
| GET | `/staff/attendees` | 🛡️ | ค้นหา attendees (share `query_attendees` กับ admin) |
| POST | `/staff/checkin/manual` | 🛡️ | `{user_id, event_day, gate?}` → `CheckinOut` — เช็คชื่อมือ (ไม่มี undo สำหรับ staff) |
| POST | `/staff/coins/grant` | 🛡️ | `{user_id/ticket_code/student_id, amount, device_id}` → `CoinGrantOut` — จ่าย coin บูธ, ผ่าน quota 4 ชั้น + cooldown 20s |

---

## admin — `/admin` (👑 admin)

### แดชบอร์ด / ผู้ใช้
| Method | Path | หน้าที่ |
|---|---|---|
| GET | `/admin/dashboard` | counts: users/checkins/votes/ig/spins |
| GET | `/admin/users?q=&cursor=` | ค้นหา user (regex escaped) |
| POST | `/admin/users/{user_id}/points` | `{amount, reason, note}` — ปรับ coin (idempotent by time) |
| POST | `/admin/users/{user_id}/roles` | `{roles}` — set role (ไม่ demote ตัวเอง, `superadmin` DB-only) |

### เช็คอิน
| Method | Path | หน้าที่ |
|---|---|---|
| GET | `/admin/attendees?q=&event_day=&status=&cursor=` | รายชื่อ + checked_in_days |
| POST | `/admin/checkin/manual` | `{user_id, event_day, gate?}` → `CheckinOut` |
| POST | `/admin/checkin/undo` | `{user_id, event_day}` → ล้าง Mongo + Redis dedupe (ไม่คืน coin) |

### Quests (CRUD)
| Method | Path | หน้าที่ |
|---|---|---|
| GET | `/admin/quests` | ทุก quest (รวม closed) + claimed count |
| POST | `/admin/quests` | `{quest_key, title, description, coins, max_per_user, sort_order}` → 201 |
| PATCH | `/admin/quests/{quest_key}` | update |
| DELETE | `/admin/quests/{quest_key}` | delete (ถ้ามี claim → ปิดแทน เก็บ ledger) |

### Staff grant monitoring
| Method | Path | หน้าที่ |
|---|---|---|
| GET | `/admin/grants/summary` | totals + by_staff + by_user + **staff↔receiver pairs** (สัญญาณทุจริต) + limits |
| POST | `/admin/grants/reset-budget/{staff_id}` | reset budget รายวันของ staff (ไม่แตะ pair/receive) |

### รอบโหวต / IG
| Method | Path | หน้าที่ |
|---|---|---|
| POST | `/admin/vote-rounds/{round_key}/{action}` | `open`/`close`/`publish` (close = freeze tally → Mongo) |
| GET | `/admin/ig/queue?status=` | คิว IG (มี image_data/caption/handle) limit 20 |
| POST | `/admin/ig/{submission_id}/approve` | อนุมัติ (ไม่ให้ coin — ส่งมอบช่อง) |
| POST | `/admin/ig/{submission_id}/reject?reason=` | ปฏิเสธ + refund `IG_WALL_COST` |
| POST | `/admin/ig/wall/clear` | mark ทุก approved เป็น shown (reset วันใหม่) |

### Config / Audit / Ops
| Method | Path | หน้าที่ |
|---|---|---|
| PATCH | `/admin/config` | `{maintenance_mode?, read_only_mode?, features?, announcement?}` — มีผล 5 วิ |
| GET | `/admin/audit-logs?action=&cursor=` | audit trail + join actor name |
| GET | `/admin/audit-logs/actions` | distinct actions (สำหรับ dropdown filter) |
| POST | `/admin/reconcile/points?fix=true` | แก้ balance ให้ตรง ledger |
| POST | `/admin/rebuild/leaderboard` | rebuild Redis `lb:coins` จาก Mongo |

---

## exports — `/admin/export` (👑 admin, CSV)

ทั้งหมด streaming CSV (UTF-8 BOM, `\r\n`, เวลา +07:00, Excel-friendly)

| Method | Path | หน้าที่ |
|---|---|---|
| GET | `/admin/export/checkins.csv?event_day=&result=` | ทุกการสแกน (รวม reject) + join user/staff |
| GET | `/admin/export/attendees.csv` | 1 แถว/คน + mark วันเช็ค + ยอด coin |
| GET | `/admin/export/coins.csv?reason=` | ledger เต็ม + `balance_after` + reason ไทย + actor |

---

## ตัวอย่าง request/response

### `POST /v1/checkin` (staff สแกน)
```bash
curl -X POST https://api.../v1/checkin \
  -H "Authorization: Bearer <staff_jwt>" \
  -H "Idempotency-Key: 01JABC..." \
  -H "Content-Type: application/json" \
  -d '{"payload":"EGOKE2:1:EGOKE26-6DFF226B:1786...:1S2l...","event_day":1,"device_id":"scanner-01","gate":"MAIN"}'
```
```json
{
  "result": "ok",
  "event_day": 1,
  "user": {"display_name": "PP", "avatar_url": "...", "student_id": "6500000"},
  "ticket": {"event_day": 1, "tier": "general"},
  "coins_awarded": 10,
  "checked_in_at": "2026-08-10T09:00:00Z",
  "checked_in_gate": "MAIN"
}
```

### `GET /v1/me/stream` (SSE)
```
retry: 5000

event: checkin_ok
data: {"uid":"...","type":"checkin_ok","event_day":1,"coins_awarded":10,"form_url":"https://forms.gle/...","at":"..."}

: ping

```

### Error
```json
{
  "error": {
    "code": "INSUFFICIENT_COINS",
    "message": "เหรียญไม่พอ ต้องมีอย่างน้อย 20 เหรียญ",
    "message_en": "Insufficient coins",
    "details": {"required": 20, "balance": 5},
    "request_id": "01JABCD..."
  }
}
```

---

## Config ที่คุมพฤติกรรม API

ดู `backend/app/core/config.py` + [05-infrastructure.md](05-infrastructure.md) สำหรับรายละเอียดเต็ม ค่าสำคัญ:

| Config | Default | กระทบ |
|---|---|---|
| `ALLOWED_EMAIL_DOMAINS` | `""` (รับทั้งหมด) | login จำกัด domain |
| `ADMIN_EMAILS` | `""` | promote admin ตอน login |
| `CHECKIN_COINS` | `10` | coin ต่อวันเช็คอิน |
| `STAFF_GRANT_*` | `200/300/1500/20000` | quota 4 ชั้น staff grant |
| `WALL_COST` (ใน ig.py) | `20` | coin ที่จ่ายส่ง IG |
| `ATTENDANCE_FORM_URL` | `""` | ลิงก์ Google Form ใน modal |
| `STRICT_QR_MODE` | `false` | บังคับ TOTP rotating code |
| `REQUIRE_CHECKIN_TO_VOTE` | `false` | ต้องเช็คอินก่อนโหวต |
| `DISPLAY_TOKEN` | `""` | gate WS + ig-wall shown |
| `features.*` | (ใน system_config) | toggle ฟีเจอร์ผ่าน `/admin/config` |
