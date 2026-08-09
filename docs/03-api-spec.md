# 03 — API Specification

Base URL: `https://api.egoke2026.example/v1`
Content-Type: `application/json`
OpenAPI อัตโนมัติที่ `/docs` (ปิดใน production ด้วย env `ENABLE_DOCS=false`)

## Conventions

| หัวข้อ | กติกา |
|---|---|
| Auth | `Authorization: Bearer <access_token>` (JWT, อายุ 15 นาที) |
| Refresh | httpOnly + Secure + SameSite=Lax cookie `rt` (อายุ 30 วัน, rotate ทุกครั้ง) |
| Idempotency | `Idempotency-Key: <uuid>` — **บังคับ** ทุก POST ที่เปลี่ยน state |
| Versioning | prefix `/v1` |
| Pagination | cursor-based: `?limit=50&cursor=<opaque>` (ห้ามใช้ skip/offset) |
| Timestamps | ISO 8601 UTC เสมอ (`2026-08-05T12:00:00Z`) — frontend แปลงเป็น +07:00 เอง |

### Error model (เหมือนกันทุก endpoint)
```json
{
  "error": {
    "code": "VOTE_ROUND_CLOSED",
    "message": "รอบโหวตนี้ปิดแล้ว",
    "message_en": "This voting round is closed.",
    "details": { "round_key": "d2-main", "closed_at": "2026-11-14T15:00:00Z" },
    "request_id": "01JABCD..."
  }
}
```
`request_id` เป็น ULID ใส่ใน response header `X-Request-ID` ด้วย → staff บอกเลขนี้มา เราเปิด log เจอทันที

### HTTP status ที่ใช้
`200` ok · `201` created · `202` accepted (queued) · `400` validation · `401` no/bad token · `403` no permission · `404` · `409` conflict/duplicate · `422` semantic error · `429` rate limited (มี `Retry-After`) · `503` degraded mode

---

## 1. Auth — `/auth`

### `GET /auth/google/login`
เริ่ม OAuth flow
```
Query: ?redirect_uri=https://egoke2026.example/callback
→ 302 ไป accounts.google.com พร้อม PKCE code_challenge
   (state + code_verifier เก็บใน Redis อายุ 10 นาที)
```

### `POST /auth/google/callback`
```jsonc
// Request
{ "code": "4/0Ade...", "state": "..." }

// 200
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": { "id": "...", "email": "...", "display_name": "PP",
            "roles": ["participant"], "points_balance": 0,
            "needs_onboarding": true }
}
// + Set-Cookie: rt=...; HttpOnly; Secure; SameSite=Lax; Path=/v1/auth
```
**การตรวจสอบ:**
1. แลก `code` → id_token ที่ Google
2. verify signature ด้วย Google JWKS (cache 24 ชม.)
3. เช็ค `aud` == client_id, `iss`, `exp`
4. เช็ค `email_verified == true`
5. เช็ค domain — **`ALLOWED_EMAIL_DOMAINS` ปล่อยว่างไว้ = รับทุก domain (ค่าที่ใช้อยู่จริง)**
   หน้างานคนไม่ได้ล็อกอินเมลมหิดลไว้ในมือถือ บังคับแล้วจะเป็นคอขวดที่ประตู
   ถ้าใส่ค่าเมื่อไหร่จะกลับไปจำกัด แล้วคนนอกได้ `403 EMAIL_DOMAIN_NOT_ALLOWED`
6. upsert user by `google_sub`

Error: `400 OAUTH_STATE_INVALID` · `403 EMAIL_DOMAIN_NOT_ALLOWED` (เฉพาะตอนตั้ง allowlist) · `403 ACCOUNT_SUSPENDED`

**การกรอกข้อมูล** — ทุกคนต้องกรอกครบเหมือนกันหมด **ไม่แยกตาม domain ของอีเมล**:
`ชื่อเล่น · คณะ · สาขาวิชา · รหัสนักศึกษา · Instagram` (`400 PROFILE_INCOMPLETE` ถ้าขาด
พร้อม `details.missing` บอกว่าขาดอะไรบ้างทีเดียว)

★ ที่เปิดรับอีเมลทุก domain **ไม่ได้แปลว่าเปิดให้คนนอกมหาวิทยาลัยเข้างาน** —
แปลว่าคนที่หน้างานไม่ได้ล็อกอินเมลมหิดลไว้ในมือถือก็ใช้เมลอื่นเข้าได้
ตัวตนจริงมาจากข้อมูลที่กรอก ไม่ใช่จาก domain ของอีเมล
รายชื่อช่องที่ต้องกรอกอยู่ที่ `services/profile.py: REQUIRED_FIELDS` ที่เดียว —
มีเทสต์ล็อกไว้ว่าต้องตรงกับฟอร์มหน้า `/onboarding` (เพิ่มช่องที่ backend
แล้วลืมเพิ่มในฟอร์ม = ผู้ใช้กรอกจนสุดแล้วโดน 400 โดยไม่มีช่องให้กรอก)

### `POST /auth/refresh`
อ่าน cookie `rt` → ออก access token ใหม่ + rotate refresh
> ถ้าตรวจพบ **reuse** ของ token เก่า → revoke ทั้ง family + `401 TOKEN_REUSE_DETECTED`

### `POST /auth/logout`
revoke refresh token family ปัจจุบัน + ใส่ jti ลง Redis denylist จนกว่า access token จะหมดอายุ

---

## 2. Me — `/me`

| Method | Path | คำอธิบาย |
|---|---|---|
| `GET` | `/me` | โปรไฟล์ + คะแนน + สถานะบัตร (cache 10s) |
| `PATCH` | `/me` | แก้ `display_name`, `instagram_handle`, `consent` |
| `GET` | `/me/points` | ledger ของตัวเอง (paginated) |
| `GET` | `/me/tickets` | บัตรทุกวัน + QR payload |
| `GET` | `/me/votes` | โหวตไปแล้วอะไรบ้าง |
| `GET` | `/me/submissions` | สถานะ IG ที่ส่งไป |
| `GET` | `/me/spins` | ประวัติหมุนวงล้อ + รางวัลที่ยังไม่รับ |
| `GET` | `/me/export` | ★ PDPA — สำเนาข้อมูลตัวเองทั้งหมด (โปรไฟล์ + เหรียญ + โหวต) |
| `GET` | `/me/stream` | SSE push ตอนถูกเช็คอิน (auth ผ่าน query param — EventSource ส่ง header ไม่ได้) |

**`GET /me/export`** — ปุ่มอยู่ในหน้า `/profile` การ์ด "ข้อมูลของคุณ"
ตอบเป็น JSON เปล่าๆ ไม่มี `Content-Disposition` → ฝั่งเว็บตั้งชื่อไฟล์เอง
(`egoke2026-my-data.json`) ตัด `_id` กับ `google_sub` ออกก่อนส่ง

**`GET /me` — 200**
```jsonc
{
  "id": "66b1...", "email": "...", "display_name": "PP",
  "avatar_url": "...", "instagram_handle": "pp_egoke",
  "roles": ["participant"],
  "points_balance": 150,
  "rank": 42,                                 // จาก Redis ZREVRANK
  "tickets": [{ "event_day": 1, "status": "checked_in", "ticket_code": "EGOKE26-D1-..." }],
  "needs_onboarding": false
}
```

---

## 3. Tickets & QR — `/tickets`

### `GET /tickets/{event_day}/qr`
คืน payload สำหรับ render QR ที่ฝั่ง client (**ห้ามให้ server render PNG** เปลืองเปล่าๆ)
```jsonc
{
  "payload": "EGOKE2:1:EGOKE26-D1-7F3A9C21:1762089600:aGVsbG8...",
  "ticket_code": "EGOKE26-D1-7F3A9C21",
  "event_day": 1,
  "status": "issued",
  "rotating_code": "482913",     // TOTP 6 หลัก เปลี่ยนทุก 30 วิ (anti-screenshot)
  "rotates_in": 17
}
```
**รูปแบบ payload:** `EGOKE2:<qr_version>:<ticket_code>:<issued_ts>:<base64url(HMAC-SHA256)>`
HMAC ใช้ `QR_SIGNING_KEY` → scanner ตรวจได้ **โดยไม่ต้องต่อเน็ต**

### `POST /checkin` 🔒 staff
```jsonc
// Request  — Idempotency-Key: <uuid> บังคับ
{
  "payload": "EGOKE2:1:EGOKE26-D1-...:1762089600:aGVs...",
  "rotating_code": "482913",       // optional, บังคับถ้า STRICT_QR_MODE=true
  "gate": "GATE-A",
  "device_id": "scanner-03",
  "scanned_at": "2026-11-13T10:02:11Z"
}

// 200 ผ่าน
{ "result": "ok", "user": { "display_name": "PP", "avatar_url": "...", "student_id": "6512345" },
  "ticket": { "event_day": 1, "tier": "general" }, "points_awarded": 10 }

// 409 สแกนซ้ำ — ยังคืน 200-shape ให้ scanner แสดงผลได้
{ "result": "duplicate", "checked_in_at": "2026-11-13T09:41:03Z",
  "checked_in_gate": "GATE-B",
  "user": { "display_name": "PP", "avatar_url": "..." } }
```
`result` ที่เป็นไปได้: `ok` · `duplicate` · `invalid_sig` · `revoked` · `wrong_day` · `expired` · `rotating_code_mismatch`

> **Scanner UX:** สีเขียว=ok / สีเหลือง=duplicate (ยังให้เข้า แจ้ง staff) / สีแดง=อื่นๆ
> เสียงต่างกัน 3 แบบ เพราะหน้างานเสียงดัง staff ไม่ได้มองจอ

### `POST /checkin/batch` 🔒 staff — สำหรับ offline queue
```jsonc
{ "items": [ {...}, {...} ] }   // สูงสุด 100 รายการ
// 200
{ "results": [ { "idempotency_key": "...", "result": "ok" }, ... ] }
```
scanner เก็บใน IndexedDB ตอนเน็ตหลุด แล้วยิงชุดนี้ตอนเน็ตกลับมา

---

## 4. Voting — `/votes`

### `GET /vote-rounds`
```jsonc
{ "rounds": [{
    "round_key": "d2-main", "title": "โหวตศิลปินหลัก", "status": "open",
    "opens_at": "...", "closes_at": "...", "results_public": false,
    "max_votes_per_user": 1,
    "candidates": [{ "id": "...", "name": "ศิลปิน A", "image_url": "...", "sort_order": 1 }],
    "my_vote": null                                  // artist_id ถ้าเคยโหวตแล้ว
}]}
```

### `POST /votes` ⭐ hot path
```jsonc
// Request — Idempotency-Key บังคับ
{ "round_key": "d2-main", "artist_id": "66b2..." }

// 202 Accepted
{ "accepted": true, "round_key": "d2-main", "artist_id": "66b2...",
  "already_voted": false, "results_visible": false }

// 200 (โหวตซ้ำ — ไม่ใช่ error, คืนของเดิม)
{ "accepted": true, "artist_id": "66b2...", "already_voted": true }
```
Errors: `403 VOTE_ROUND_CLOSED` · `403 NOT_CHECKED_IN` (ถ้าเปิด requirement) · `429 RATE_LIMITED` · `503 VOTING_DISABLED`

**เส้นทางประมวลผล:** Redis Lua atomic → `202` ทันที → worker เขียน Mongo ทีหลัง
**ห้ามคืน 500 เด็ดขาด** ถ้า Mongo ล่ม — Redis สำเร็จแล้วคือโหวตติดแล้ว

### `GET /vote-rounds/{round_key}/results`
ถ้า `results_public=false` และไม่ใช่ admin → `403 RESULTS_HIDDEN`
```jsonc
{ "round_key": "d2-main", "total_votes": 3421,
  "results": [{ "artist_id": "...", "name": "ศิลปิน A", "votes": 1820, "percent": 53.2 }],
  "as_of": "2026-11-14T14:32:10Z", "is_final": false }
```

---

## 5. Instagram — `/ig`

### `POST /ig/submissions`
```jsonc
{ "post_url": "https://www.instagram.com/p/CxYz123ABC/" }
// 201
{ "id": "...", "shortcode": "CxYz123ABC", "status": "pending",
  "queue_position": 12, "estimated_points": 50 }
```
Errors: `400 INVALID_IG_URL` · `409 SHORTCODE_ALREADY_SUBMITTED` · `429 SUBMISSION_LIMIT` (5/วัน)

Server แกะ shortcode จาก URL แล้ว normalize — กัน `?igshid=` และ URL หลายรูปแบบมา bypass unique index

### `GET /ig/leaderboard`  (cache 5s, public)
```jsonc
{ "top": [{ "rank": 1, "display_name": "PP", "instagram_handle": "pp_egoke",
            "avatar_url": "...", "approved_count": 8, "points": 400 }],
  "my_rank": 42, "as_of": "..." }
```

---

## 6. Wheel — `/wheel`

### `GET /wheel/{wheel_key}`
```jsonc
{ "wheel_key": "main-wheel", "title": "วงล้อรางวัลใหญ่",
  "cost_points": 20, "status": "open",
  "segments": [{ "id": "s1", "label": "เสื้อ EG'OKE", "prize_type": "physical", "sold_out": false }],
  "commit_hash": "sha256:9f2a...",       // ★ ประกาศก่อนงาน = พิสูจน์ว่าไม่ล็อกผล
  "my_spins_used": 1, "my_spins_left": 2, "my_points": 150 }
```
> **ไม่ส่ง `weight` ให้ client** ไม่งั้นคนคำนวณ EV แล้วบ่นว่าโกง

### `POST /wheel/{wheel_key}/spin`
```jsonc
// Request — Idempotency-Key บังคับ
{ "client_seed": "abc123", "nonce": 2 }

// 200
{ "spin_id": "...",
  "result_segment_id": "s2",
  "segment_index": 4,           // ★ frontend ใช้เลขนี้คำนวณองศาให้ล้อหยุดตรงช่อง
  "label": "+50 คะแนน",
  "prize_type": "points", "points_won": 50,
  "points_spent": 20, "points_balance": 180,
  "proof": { "nonce": 2, "client_seed": "abc123", "hmac": "a1b2c3..." } }
```
Errors: `402 INSUFFICIENT_POINTS` · `403 SPIN_LIMIT_REACHED` · `409 WHEEL_CLOSED` · `409 NONCE_ALREADY_USED`

**ลำดับที่ server ทำ (ห้ามสลับ):**
1. หัก points ก่อน (ledger `wheel_cost`) — ถ้าหักไม่ได้ จบ
2. `HMAC-SHA256(server_seed, f"{client_seed}:{nonce}")` → int → mod ผลรวม weight → หา segment
3. ถ้า segment มี stock → `$inc remaining:-1` แบบมีเงื่อนไข `remaining > 0`; ถ้าล้มเหลว → ตกไป segment "ไม่ถูกรางวัล"
4. บันทึก spin + ให้ points ถ้าเป็นรางวัลคะแนน (ledger `wheel_prize`)
5. publish event `wheel.result` ให้จอ

> **frontend มีหน้าที่แค่หมุนให้หยุดตรง `segment_index`** ห้ามสุ่มเอง — ไม่งั้นเปิด DevTools ก็โกงได้

### `GET /wheel/{wheel_key}/verify` — เปิดหลังจบงาน
คืน `server_seed` จริง → ใครก็ตรวจสอบย้อนหลังได้ว่า `sha256(server_seed) == commit_hash` และคำนวณผลซ้ำได้ทุกใบ

---

## 7. Live / Public — `/live` (ไม่ต้อง auth, cache หนัก)

| Path | Cache | ใช้ที่ไหน |
|---|---|---|
| `GET /live/snapshot` | 1s Nginx + 2s CDN | มือถือ poll ทุก 3 วิ |
| `GET /live/leaderboard?type=points\|ig` | 5s | หน้า leaderboard |
| `GET /live/checkin-stats` | 3s | การ์ดสถิติสดในหน้า `/staff` (`CheckinStatsCard`) — poll ทุก 5 วิ |
| `GET /live/ig-wall` | 5s | คิวจอ IG — ★ คืนเฉพาะใบที่ยังไม่เคยขึ้นจน |
| `POST /live/ig-wall/{id}/shown?token=` | — | จอแจ้งว่าฉายครบ 45 วิแล้ว → ตัดออกจากคิวถาวร (ต้องมี `DISPLAY_TOKEN`) |

**คิวจอ IG — "ขึ้นคนละหนึ่งรอบ" ไม่วนซ้ำ**
คนจ่าย 20 เหรียญเพื่อได้ขึ้นจอหนึ่งรอบ ไม่ใช่เพื่อยึดจอทั้งงาน
ใบที่ฉายครบเวลาจะถูกทำเครื่องหมาย `wall_shown_at` แล้วหลุดจากคิวถาวร

★ **จอเป็นคนแจ้งว่าฉายจบ ไม่ใช่ backend จับเวลาเอง** — ถ้า backend นับเอง
คิวจะไหลทิ้งแม้ไม่มีใครเปิดจอ (คนจ่ายตอนดึกแล้วสิทธิ์หมดโดยไม่มีใครเห็น)
ทางนี้ถ้าจอดับ ใบนั้นค้างคิวไว้ รอบหน้าเปิดมาก็ได้ฉายต่อ

★ **ต้องเปิดจอด้วย `/display/ig?token=<DISPLAY_TOKEN>`** ไม่งั้นแจ้งไม่ได้
= คิวไม่เดิน วนใบเดิมเหมือนเดิม (หน้าจอขึ้นกล่องเตือนสีเหลืองให้เห็นชัด)
| `WS /live/ws` | — | จอแสดงผลเท่านั้น (ต้องมี display token) |
| `GET /live/sse` | — | fallback ถ้า WS โดน block |

**`GET /live/snapshot`**
```jsonc
{
  "server_time": "2026-11-14T14:32:10Z",
  "seq": 84213,                          // เพิ่มเรื่อยๆ — client เทียบว่าข้อมูลใหม่ไหม
  "active_round": { "round_key": "d2-main", "status": "open", "closes_in": 245,
                    "results_public": false,
                    "tally": [{ "artist_id": "...", "name": "ศิลปิน A", "votes": 1820 }] },
  "checkins": { "today": 2431, "total": 4102, "rate_per_min": 18 },
  "top_points": [{ "rank": 1, "display_name": "PP", "points": 980 }],
  "top_ig":     [{ "rank": 1, "instagram_handle": "pp_egoke", "approved_count": 8 }],
  "announcement": { "text": "", "level": "info" },
  "features": { "voting": true, "wheel": true, "ig_submission": true }
}
```
สร้างโดย `broadcaster` ทุก 1 วินาที เก็บใน Redis key `live:snapshot` — API แค่ `GET` ออกมาเฉยๆ ไม่คำนวณอะไรเลย

---

## 8. Admin — `/admin` 🔒 role: admin|superadmin

| Method | Path | คำอธิบาย |
|---|---|---|
| `GET` | `/admin/dashboard` | KPI รวม: ลงทะเบียน/เช็คอิน/โหวต/คิว IG |
| `GET` | `/admin/users` | ค้นหา + filter + export CSV |
| `PATCH` | `/admin/users/{id}` | เปลี่ยน role / suspend |
| `POST` | `/admin/users/{id}/points` | ปรับคะแนนด้วยมือ (**ต้องมี `note` บังคับ**) |
| `GET` | `/admin/ig/queue?status=pending` | คิว moderation |
| `POST` | `/admin/ig/{id}/approve` | อนุมัติ + ให้คะแนน |
| `POST` | `/admin/ig/{id}/reject` | ปฏิเสธ + เหตุผล |
| `POST` | `/admin/ig/bulk` | อนุมัติ/ปฏิเสธทีละหลายอัน |
| `POST` | `/admin/vote-rounds` | สร้างรอบโหวต |
| `POST` | `/admin/vote-rounds/{k}/open\|close\|publish` | คุมรอบโหวต |
| `POST` | `/admin/wheel/{k}/trigger` | หมุนวงล้อบนเวที (broadcast ไปทุกจอ) |
| `PATCH` | `/admin/config` | ⚡ feature flags / maintenance / ประกาศ |
| `GET` | `/admin/audit-logs` | ประวัติทุก action |
| `POST` | `/admin/reconcile/points` | ซ่อม balance ให้ตรง ledger |
| `GET` | `/admin/export/{collection}` | dump CSV/JSON |

### `POST /admin/users/{id}/points`
```jsonc
{ "amount": 50, "reason": "admin_adjust", "note": "ชดเชยระบบล่มรอบ 20:15" }
// 200
{ "transaction_id": "...", "new_balance": 200 }
```
> ทุก endpoint ใน `/admin` เขียน `audit_logs` อัตโนมัติผ่าน middleware — ไม่มีข้อยกเว้น

---

## 9. Health / Ops

| Path | ใช้ทำอะไร |
|---|---|
| `GET /healthz` | liveness — คืน 200 เสมอถ้า process ยังอยู่ |
| `GET /readyz` | readiness — เช็ค Redis + Mongo, ใช้ตัดสินว่า Nginx ส่ง traffic มาไหม |
| `GET /metrics` | Prometheus (จำกัด IP ภายใน) |
| `GET /version` | git sha + build time |

> `healthz` กับ `readyz` ต้องแยกกัน — ถ้า Mongo ช้าเราอยากให้ `readyz` fail (หยุดรับ traffic ใหม่)
> แต่ `healthz` ต้องผ่าน (อย่าให้ Docker restart ทิ้ง)

---

## 10. Rate Limits

| Endpoint | Limit | Key | เหตุผล |
|---|---|---|---|
| `POST /auth/google/callback` | 10 / 5 นาที | IP | กัน brute force |
| `POST /votes` | 30 / นาที | user_id | คนจริงกดไม่เกินนี้ |
| `POST /ig/submissions` | 5 / วัน | user_id | ตามกติกางาน |
| `POST /wheel/*/spin` | 10 / นาที | user_id | |
| `POST /checkin` | 300 / นาที | device_id | staff สแกนรัวได้ |
| `GET /live/*` (login แล้ว) | 120 / นาที | **user_id** | poll ทุก 3 วิ = 20/นาที มี headroom 6 เท่า |
| `GET /live/*` (ยังไม่ login) | 3,000 / นาที | IP | จอใหญ่ + คนที่ยังอยู่หน้า login แชร์ IP เดียวกัน |
| default | 100 / นาที | user_id หรือ IP | |

Response 429:
```
Retry-After: 12
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1762089612
```
Algorithm: **sliding window counter ใน Redis** (แม่นกว่า fixed window, ถูกกว่า sliding log)

> ⚠️ ระวัง: ผู้เข้าร่วมทั้งงานอยู่หลัง WiFi/4G NAT เดียวกัน → **rate limit ต่อ IP จะฆ่าทุกคนพร้อมกัน**
> ดังนั้น endpoint ที่ต้อง auth ให้ใช้ `user_id` เป็น key เสมอ ใช้ IP เฉพาะ endpoint ที่ไม่มี auth

> ★ `GET /live/*` เคยพลาดกฎข้อบนนี้ — ตั้งไว้ 120/นาที **ต่อ IP** ทั้งที่ทุกคนเรียก
> load test จับได้: 5,000 เครื่อง × 20 ครั้ง/นาที = 100,000 ครั้ง/นาทีจาก IP เดียว
> → ทุกคนโดน 429 พร้อมกันตั้งแต่วินาทีแรกของงาน
> ตอนนี้ใช้ `ratelimit.check_public()` ซึ่งเลือก bucket ตาม token ก่อน แล้วค่อยตกไปที่ IP
> รายละเอียด: [13-testing-and-load.md](13-testing-and-load.md#41-rate-limit-ต่อ-ip-จะฆ่าทุกคนพร้อมกันหลัง-nat)

---

## 11. Endpoint ที่เพิ่ม/แก้รอบล่าสุด

| Method | Path | หมายเหตุ |
|---|---|---|
| `GET` | `/ig/config` | **ใหม่** — ราคา/ขนาดรูปสูงสุด/รูปแบบ handle ให้ frontend อ่านแทน hardcode |
| `GET` | `/ig/image/{id}` | **ใหม่** — รูปของโพสต์ที่อนุมัติแล้ว, `Cache-Control: max-age=86400, immutable` |
| `GET` | `/admin/audit-logs` | **แก้** — เคย 500 ทุกครั้ง (ObjectId + ORJSON) ตอนนี้คืน `items` + `next_cursor` + ชื่อ admin |
| `GET` | `/admin/audit-logs/actions` | **ใหม่** — รายการ action ที่มีจริง ใช้ทำ dropdown กรอง |
| `GET` | `/me/submissions` | **แก้** — คีย์เปลี่ยนจาก `submissions` → `items`, เพิ่ม `instagram_handle` / `caption` / `reviewed_at`, ตัด base64 ออก |
| `GET` | `/live/ig-wall` | **แก้** — คืน `image_url` แทน `image_data` (base64) |
| `POST` | `/admin/ig/{id}/approve` | **แก้** — ไม่จ่ายเหรียญแล้ว (เดิมจ่ายคืน 50 ทั้งที่หักไป 20 = ส่งรูปแล้วได้กำไร) |
| `POST` | `/admin/ig/{id}/reject` | **แก้** — คืนเหรียญค่าส่งให้ผู้ใช้, response เพิ่ม `coins_refunded` / `new_balance` |
| `POST` | `/wheel/{key}/spin` | **แก้** — nonce ชนหรือหมุนเกินโควตา → คืนเหรียญก่อน raise |
| `GET` | `/ig/leaderboard` | **ลบแล้ว** — ไม่มีหน้าอันดับในระบบ |
| `GET` | `/staff/attendees` | **ใหม่** — ค้นรายชื่อ (ตรรกะเดียวกับ `/admin/attendees`) 🔒 staff |
| `POST` | `/staff/checkin/manual` | **ใหม่** — เช็คชื่อด้วยมือ 🔒 staff · **ไม่มีคู่ยกเลิก** (undo เป็นสิทธิ์ admin) |
| `POST` | `/admin/users/{id}/roles` | **ใหม่** — ตั้งสิทธิ์ `[] / ["staff"] / ["admin"]` (ส่งชุดเต็ม) `participant` ระบบใส่ให้เอง · ถอด admin ของตัวเองไม่ได้ (`400 CANNOT_DEMOTE_SELF`) · **มีผลเมื่อ token รอบใหม่ (≤15 นาที)** |
| `GET` | `/admin/export/checkins.csv` | **ใหม่** — ประวัติการสแกนทั้งหมด (`?event_day=` `?result=`) |
| `GET` | `/admin/export/attendees.csv` | **ใหม่** — รายชื่อ 1 คน 1 แถว + สรุปว่าเข้าวันไหนบ้าง |
| `POST` | `/staff/coins/grant` | **ใหม่** — staff เลือกจำนวนแล้วสแกนจ่าย 🔒 staff · เพดาน 1000/ครั้ง · กัน 2 ชั้น: `Idempotency-Key` (ยิงซ้ำ) + cooldown 20 วิ ต่อ (เครื่อง, บัตร) (กล้องอ่าน QR ซ้ำ) · ลง audit ทุกครั้ง |
| `GET` | `/admin/grants/summary` | **ใหม่** — เฝ้าดูการจ่ายเหรียญ: ยอดรวม · staff ที่จ่าย · ผู้รับ · **คู่ staff→ผู้รับที่จ่ายกันเยอะสุด** (สัญญาณจ่ายให้พวกพ้อง) |
| `POST` | `/admin/grants/reset-budget/{staff_id}` | **ใหม่** — ล้างเบรกเกอร์รายวันของ staff · **ไม่ล้าง**โควตาต่อผู้รับ/ผู้รับต่อวัน (สองอันนั้นคือด่านกันพวกพ้อง ล้างได้ = ไม่มีด่าน) |
| `GET` | `/admin/export/coins.csv` | **ใหม่** — ทุกการเคลื่อนไหวของเหรียญ (`?reason=staff_grant` = กระทบยอดกับบูธ) |
| `POST` | `/quests/claim` | **เลิกใช้** — เครื่องสแกนเปลี่ยนไปใช้ `/staff/coins/grant` แทน (บูธเก็บค่าเล่นเป็นเงินสด ไม่ผูกกับกิจกรรม) |
| `PATCH` | `/me` | **แก้** — ต้องกรอกครบทุกช่องก่อนจบ onboarding (`400 PROFILE_INCOMPLETE` + `details.missing`) |
| `GET` | `/me` | **แก้** — `needs_onboarding` เป็น true ถ้ายังกรอกไม่ครบ (ดึงคนที่สมัครช่วงแรกกลับมากรอกให้ครบ) |

**โควตาการจ่ายเหรียญ** — `staff_grant` เป็นทางเดียวที่เหรียญเข้าระบบได้แบบไม่มีเพดานในตัว
(เช็คอินปิดด้วย dedupe รายวัน · กิจกรรมจำกัดครั้ง/คน · วงล้อ EV −1 + 3 ครั้ง/คน)
4 ชั้น แต่ละชั้นปิดคนละช่องโหว่ ตั้งค่าใน `.env` แล้ว restart (~5 วิ):

| ชั้น | ค่าเริ่มต้น | ปิดช่องโหว่อะไร |
|---|---|---|
| `STAFF_GRANT_MAX_PER_SCAN` | 200 | พิมพ์ผิดหลัก (ตั้งใจ 100 พิมพ์ 1000) |
| `STAFF_GRANT_PER_USER_DAILY` | 300 | **staff จ่ายให้เพื่อนรัวๆ** |
| `USER_GRANT_RECEIVE_DAILY` | 1500 | **ไล่เก็บจาก staff หลายคน** (ชั้นบนกันได้ทีละคน ชั้นนี้ปิดท้าย) |
| `STAFF_GRANT_DAILY_BUDGET` | 20000 | เครื่องสแกนหลุดมือ (เบรกเกอร์ ตั้งหลวม) |

จองโควตา **ก่อน** จ่าย ไม่ใช่บันทึกหลังจ่าย — ถ้านับหลังจ่าย ยอดที่เกินก็เข้ากระเป๋าไปแล้ว
ครั้งที่ถูกปฏิเสธไม่กินโควตาและไม่ติด cooldown นับวันตามปฏิทินไทย ไม่ใช่ UTC
(ตัดด้วย UTC = โควตารีเซ็ตตอน 7 โมงเช้าซึ่งอยู่กลางงาน)

**CSV export — 3 อย่างที่ทำให้เปิดใน Excel ได้จริง** (พังเงียบถ้าขาด):
1. **BOM นำหน้าไฟล์** — ขาดแล้วภาษาไทยเป็นขยะทั้งไฟล์ กู้จากในโปรแกรมไม่ได้
2. **เวลารูปแบบ `YYYY-MM-DD HH:MM:SS`** — ส่ง ISO 8601 ไป Excel อ่านเป็นข้อความ เรียงผิด
3. **แปลงเป็นเวลาไทยก่อน** — ข้อมูลใน Mongo เป็น UTC ไม่แปลงแล้วเพี้ยน 7 ชั่วโมงทุกแถว

ใช้ offset คงที่ `+07:00` ไม่ใช่ `ZoneInfo("Asia/Bangkok")` — ZoneInfo ต้องมี tzdata ใน image
ถ้าไม่มีจะพังตอน runtime เท่านั้น (import ผ่าน เทสต์ผ่าน แต่กดดาวน์โหลดจริงแล้ว 500)
