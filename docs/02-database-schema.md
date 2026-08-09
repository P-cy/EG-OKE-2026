# 02 — MongoDB Schema Design

Database: `egoke2026`

## หลักการที่ใช้ตัดสินใจ

1. **Embed สิ่งที่อ่านคู่กันเสมอ, reference สิ่งที่โตไม่จำกัด**
2. **คะแนน = append-only ledger** ห้ามมี `points: int` ที่แก้ทับได้เป็น source of truth
3. **ทุก write ที่เกิดจาก user action ต้องมี unique index กันซ้ำ** (idempotency ที่ระดับ DB)
4. **แยก collection ที่ write หนัก ออกจาก collection ที่ read หนัก** — `votes` เขียนอย่างเดียว, `vote_tallies` อ่านอย่างเดียว
5. **ใส่ `schema_version` ทุก doc** กติกางานเปลี่ยนก่อนงาน 2 วันเสมอ

---

## 1. `users`

```jsonc
{
  "_id": ObjectId,
  "email": "phatthanasak.kra@student.mahidol.ac.th",  // unique, lowercase
  "email_domain": "student.mahidol.ac.th",             // denormalize เพื่อ filter
  "google_sub": "104839...",                           // unique, sparse — Google subject ID
  "student_id": "6913099",                             // จาก email prefix หรือกรอกเอง
  "display_name": "PP",
  "full_name": "Phatthanasak Kraiduang",
  "avatar_url": "https://lh3.googleusercontent.com/...",
  "faculty": "Engineering",
  "department": "Computer"
  "instagram_handle": "pp_egoke",                      // nullable
  "roles": ["participant"],                            // participant|staff|admin|superadmin|display
  "status": "active",                                  // active|suspended|banned
  "points_balance": 0,                                 // ⚠️ cache เท่านั้น — ของจริงอยู่ใน ledger
  "points_updated_at": ISODate,
  "consent": { "tos": true, "photo": true, "at": ISODate },
  "last_login_at": ISODate,
  "login_count": 3,
  "created_at": ISODate,
  "updated_at": ISODate,
  "schema_version": 1
}
```

**Indexes**
```js
db.users.createIndex({ email: 1 },        { unique: true })
db.users.createIndex({ google_sub: 1 },   { unique: true, sparse: true })
db.users.createIndex({ student_id: 1 },   { unique: true, sparse: true })
db.users.createIndex({ points_balance: -1, _id: 1 })   // leaderboard fallback ถ้า Redis ล่ม
db.users.createIndex({ roles: 1, status: 1 })
db.users.createIndex({ instagram_handle: 1 }, { sparse: true })
```

> `points_balance` เก็บไว้เพื่อ **อ่านเร็ว** เท่านั้น มี job reconcile กับ ledger ทุก 5 นาที
> ถ้าไม่ตรงกัน → alert + ยึด ledger เป็นหลัก

---

## 2. `tickets` — บัตรเข้างาน

```jsonc
{
  "_id": ObjectId,
  "ticket_code": "EGOKE26-D1-7F3A9C21",   // unique, human-readable, พิมพ์ใส่บัตรได้
  "user_id": ObjectId,
  "event_day": 1,                          // 1|2|3
  "tier": "general",                       // general|vip|staff
  "qr_payload_hash": "sha256:...",         // hash ของ payload ที่ออกให้ (audit)
  "qr_version": 2,                          // เพิ่มเลขนี้ = ยกเลิก QR เก่าทั้งหมด
  "status": "issued",                       // issued|checked_in|revoked|expired
  "issued_at": ISODate,
  "checked_in_at": ISODate,                 // null จนกว่าจะสแกน
  "checked_in_by": ObjectId,                // staff user id
  "checked_in_gate": "GATE-A",
  "revoked_reason": null,
  "created_at": ISODate,
  "schema_version": 1
}
```

**Indexes**
```js
db.tickets.createIndex({ ticket_code: 1 },            { unique: true })
db.tickets.createIndex({ user_id: 1, event_day: 1 },  { unique: true })  // 1 คน 1 ใบ/วัน
db.tickets.createIndex({ status: 1, event_day: 1 })
db.tickets.createIndex({ checked_in_at: -1 })
```

> `{user_id, event_day}` unique คือสิ่งที่กัน double-issue ระดับ DB
> ต่อให้ API bug ยิงซ้ำ 10 ครั้ง DB ก็ปฏิเสธเอง

---

## 3. `checkins` — audit log การสแกน (append-only)

แยกจาก `tickets` เพราะ: ต้องเก็บ **ทุกครั้งที่สแกน** รวมถึงครั้งที่ถูกปฏิเสธ เพื่อสืบสวนทีหลัง

```jsonc
{
  "_id": ObjectId,
  "idempotency_key": "scan_a1b2c3",     // unique — scanner สร้าง, กันส่งซ้ำตอนเน็ตหลุด
  "ticket_id": ObjectId,
  "ticket_code": "EGOKE26-D1-7F3A9C21",
  "user_id": ObjectId,
  "result": "ok",                        // ok|duplicate|invalid_sig|revoked|wrong_day|expired
  "gate": "GATE-A",
  "device_id": "scanner-03",
  "staff_id": ObjectId,
  "scanned_at": ISODate,                 // เวลาที่สแกนจริง (จากเครื่อง)
  "received_at": ISODate,                // เวลาที่ server รับ (ต่างกันได้ถ้า offline queue)
  "offline_queued": false,
  "schema_version": 1
}
```

**Indexes**
```js
db.checkins.createIndex({ idempotency_key: 1 }, { unique: true })
db.checkins.createIndex({ ticket_id: 1, scanned_at: -1 })
db.checkins.createIndex({ scanned_at: -1 })
db.checkins.createIndex({ result: 1, scanned_at: -1 })   // dashboard "มีคนสแกนซ้ำกี่ครั้ง"
```

---

## 4. `artists` + `vote_rounds` + `votes` + `vote_tallies`

### `artists`
```jsonc
{
  "_id": ObjectId,
  "slug": "artist-a",
  "name": "ศิลปิน A",
  "image_url": "https://cdn.../a.webp",
  "description": "...",
  "sort_order": 1,
  "active": true,
  "schema_version": 1
}
```

### `vote_rounds` — คุมว่าเปิด/ปิดโหวตเมื่อไหร่
```jsonc
{
  "_id": ObjectId,
  "round_key": "d2-main",                 // unique — ใช้เป็น key ใน Redis ด้วย
  "title": "โหวตศิลปินหลัก คืนวันที่ 2",
  "candidate_ids": [ObjectId, ObjectId],
  "status": "open",                        // draft|open|closed|published
  "max_votes_per_user": 1,
  "opens_at": ISODate,
  "closes_at": ISODate,
  "results_public": false,                 // ซ่อนผลจนกว่าจะปิด (กัน bandwagon effect)
  "final_tally": { "<artist_id>": 1234 },  // freeze ตอน close
  "created_at": ISODate,
  "schema_version": 1
}
```

### `votes` — write-heavy, ไม่เคยถูก query ตอนงาน
```jsonc
{
  "_id": ObjectId,
  "round_key": "d2-main",
  "user_id": ObjectId,
  "artist_id": ObjectId,
  "voted_at": ISODate,
  "source": "web",                          // web|kiosk
  "client_ip_hash": "sha256:...",           // hash เท่านั้น (PDPA)
  "schema_version": 1
}
```

**Indexes**
```js
db.votes.createIndex({ round_key: 1, user_id: 1 }, { unique: true })  // ★ กันโหวตซ้ำชั้นสุดท้าย
db.votes.createIndex({ round_key: 1, artist_id: 1 })
db.votes.createIndex({ voted_at: -1 })
```

> ชั้นกันโหวตซ้ำมี 2 ด่าน: **Redis `SET NX`** (เร็ว, ด่านจริง) และ **unique index นี้** (ช้ากว่า, ด่านสุดท้าย)
> ถ้า Redis หายข้อมูล (restart แล้ว AOF พัง) unique index จะยังกันให้

### `vote_tallies` — read-only snapshot ที่ persist ไว้เผื่อ Redis ตาย
```jsonc
{
  "_id": "d2-main",                         // = round_key
  "tally": { "<artist_id>": 1234 },
  "total": 4567,
  "updated_at": ISODate
}
```
broadcaster เขียนทับทุก 10 วินาที (upsert) — ใช้ warm Redis กลับมาถ้า Redis restart

---

## 5. `point_transactions` — ledger (append-only, ห้ามแก้ ห้ามลบ)

```jsonc
{
  "_id": ObjectId,
  "idempotency_key": "ig:CxYz123:approve",  // unique ★ หัวใจของทั้งระบบคะแนน
  "user_id": ObjectId,
  "amount": 50,                              // + ได้ / − เสีย
  "balance_after": 150,                      // snapshot หลังทำรายการ (debug ง่ายมาก)
  "reason": "instagram_approved",            // checkin|instagram_approved|vote_bonus|
                                             // wheel_cost|wheel_prize|admin_adjust|referral
  "ref": { "type": "ig_submission", "id": ObjectId },
  "actor_id": ObjectId,                      // ใครเป็นคนให้ (admin/system)
  "note": "อนุมัติโพสต์ IG",
  "created_at": ISODate,
  "schema_version": 1
}
```

**Indexes**
```js
db.point_transactions.createIndex({ idempotency_key: 1 }, { unique: true })
db.point_transactions.createIndex({ user_id: 1, created_at: -1 })
db.point_transactions.createIndex({ reason: 1, created_at: -1 })
db.point_transactions.createIndex({ created_at: -1 })
```

### วิธีให้คะแนนที่ถูกต้อง (atomic, idempotent)
```python
# 1) จอง idempotency key ก่อน — ถ้าซ้ำจะ DuplicateKeyError ทันที
try:
    await tx.insert_one({...})
except DuplicateKeyError:
    return already_awarded   # ปลอดภัย ไม่ให้ซ้ำ

# 2) เพิ่ม balance แบบ atomic
await users.update_one({"_id": uid}, {"$inc": {"points_balance": amount}})

# 3) sync Redis leaderboard
await redis.zincrby("lb:points", amount, str(uid))
```
ลำดับนี้สำคัญ: **จอง key ก่อน แล้วค่อย $inc** ถ้าสลับกันแล้วพังกลางทาง จะได้คะแนนซ้ำ

> ทำไมไม่ใช้ MongoDB transaction? เพราะ multi-document transaction บน replica set ช้ากว่า ~3-5 เท่า และ pattern จอง-key-ก่อนนี้ให้ผลเทียบเท่าสำหรับเคสนี้ (worst case = ledger มี แต่ balance ยังไม่อัปเดต → job reconcile ทุก 5 นาทีซ่อมให้)

---

## 6. `ig_submissions` — ส่งโพสต์ Instagram

```jsonc
{
  "_id": ObjectId,
  "user_id": ObjectId,
  "shortcode": "CxYz123ABC",                 // ดึงจาก URL — unique
  "post_url": "https://instagram.com/p/CxYz123ABC/",
  "caption_snapshot": "...",
  "screenshot_key": "ig/2026/CxYz123ABC.webp",  // object storage key
  "status": "pending",                        // pending|approved|rejected|flagged
  "points_awarded": 0,
  "reviewed_by": ObjectId,
  "reviewed_at": ISODate,
  "reject_reason": null,
  "auto_flags": ["duplicate_image", "no_hashtag"],
  "submitted_at": ISODate,
  "schema_version": 1
}
```

**Indexes**
```js
db.ig_submissions.createIndex({ shortcode: 1 },  { unique: true })   // ★ กันคนละคนส่งโพสต์เดียวกัน
db.ig_submissions.createIndex({ status: 1, submitted_at: 1 })        // คิว moderation (FIFO)
db.ig_submissions.createIndex({ user_id: 1, submitted_at: -1 })
```

---

## 7. `wheel_configs` + `wheel_spins`

### `wheel_configs`
```jsonc
{
  "_id": ObjectId,
  "wheel_key": "main-wheel",
  "title": "วงล้อรางวัลใหญ่",
  "cost_points": 20,                          // 0 = ฟรี
  "segments": [
    { "id": "s1", "label": "เสื้อ EG'OKE",  "weight": 5,   "stock": 20,  "remaining": 20, "prize_type": "physical" },
    { "id": "s2", "label": "+50 คะแนน",     "weight": 200, "stock": null,"remaining": null,"prize_type": "points", "points": 50 },
    { "id": "s3", "label": "ไม่ถูกรางวัล",  "weight": 795, "stock": null,"remaining": null,"prize_type": "none" }
  ],
  "status": "open",                            // draft|open|closed
  "max_spins_per_user": 3,
  "commit_hash": "sha256:...",                 // hash ของ server seed — ประกาศก่อนเริ่ม
  "server_seed": "...",                        // ⚠️ เก็บ encrypted, reveal หลังจบ
  "schema_version": 1
}
```

> `weight` เป็นจำนวนเต็ม ไม่ใช่ % — บวกกันเป็นเท่าไหร่ก็ได้ ไม่ต้องกลัว floating point
> `remaining` ลดด้วย `$inc: -1` พร้อมเงื่อนไข `remaining: {$gt: 0}` = atomic กันของหมดแล้วยังแจก

### `wheel_spins`
```jsonc
{
  "_id": ObjectId,
  "idempotency_key": "spin:<user>:<nonce>",   // unique
  "wheel_key": "main-wheel",
  "user_id": ObjectId,
  "nonce": 1,                                  // ลำดับการหมุนของ user คนนี้
  "client_seed": "abc123",                     // ผู้ใช้ส่งมา (ตรวจสอบได้)
  "result_segment_id": "s2",
  "result_hmac": "...",                        // HMAC(server_seed, client_seed:nonce)
  "points_spent": 20,
  "points_won": 50,
  "prize_claimed": false,
  "claimed_at": null,
  "spun_at": ISODate,
  "schema_version": 1
}
```

**Indexes**
```js
db.wheel_spins.createIndex({ idempotency_key: 1 }, { unique: true })
db.wheel_spins.createIndex({ user_id: 1, wheel_key: 1, nonce: 1 }, { unique: true })
db.wheel_spins.createIndex({ spun_at: -1 })
db.wheel_spins.createIndex({ result_segment_id: 1, prize_claimed: 1 })
```

---

## 8. `audit_logs` — ทุก action ของ admin

```jsonc
{
  "_id": ObjectId,
  "actor_id": ObjectId,
  "actor_email": "admin@mahidol.ac.th",
  "action": "points.adjust",
  "target": { "type": "user", "id": ObjectId },
  "before": { "points_balance": 100 },
  "after":  { "points_balance": 150 },
  "ip_hash": "sha256:...",
  "user_agent": "...",
  "created_at": ISODate
}
```
```js
db.audit_logs.createIndex({ created_at: -1 })
db.audit_logs.createIndex({ actor_id: 1, created_at: -1 })
db.audit_logs.createIndex({ "target.id": 1, created_at: -1 })
```

---

## 9. `refresh_tokens`

```jsonc
{
  "_id": ObjectId,
  "user_id": ObjectId,
  "token_hash": "sha256:...",       // ★ ห้ามเก็บ token ดิบ
  "family_id": "uuid",               // rotation family — reuse detection
  "device_fp": "sha256:...",
  "revoked": false,
  "replaced_by": ObjectId,
  "expires_at": ISODate,             // TTL index
  "created_at": ISODate
}
```
```js
db.refresh_tokens.createIndex({ token_hash: 1 }, { unique: true })
db.refresh_tokens.createIndex({ user_id: 1, revoked: 1 })
db.refresh_tokens.createIndex({ expires_at: 1 }, { expireAfterSeconds: 0 })  // ★ TTL ลบเองอัตโนมัติ
db.refresh_tokens.createIndex({ family_id: 1 })
```

> **Refresh token reuse detection:** ถ้า token ที่ถูก rotate ไปแล้วโดนใช้ซ้ำ = โดนขโมย
> → revoke ทั้ง `family_id` ทันที บังคับ login ใหม่

---

## 10. `system_config` — feature flags แบบเปลี่ยนสดหน้างาน

```jsonc
{
  "_id": "global",
  "maintenance_mode": false,
  "read_only_mode": false,
  "features": {
    "voting": true, "wheel": true, "ig_submission": true,
    "checkin": true, "leaderboard_public": true
  },
  "announcement": { "text": "", "level": "info", "until": ISODate },
  "updated_by": ObjectId,
  "updated_at": ISODate
}
```
โหลดเข้า Redis, cache 5 วิ — admin กดปิดฟีเจอร์แล้วมีผลใน 5 วิโดยไม่ต้อง deploy
**นี่คือคันโยกฉุกเฉินหน้างาน** ต้องมีปุ่มนี้ในหน้า admin ตัวใหญ่ๆ

---

## สรุป Index ทั้งหมด (สคริปต์รันจริงอยู่ที่ `backend/scripts/init_indexes.py`)

| Collection | ขนาดที่คาด | Docs | หมายเหตุ |
|---|---|---|---|
| `users` | ~2 MB | 5,000 | |
| `tickets` | ~5 MB | 15,000 | 5,000 × 3 วัน |
| `checkins` | ~8 MB | ~20,000 | รวม scan ที่ล้มเหลว |
| `votes` | ~15 MB | ~30,000 | หลายรอบ |
| `point_transactions` | ~30 MB | ~100,000 | ledger โตเร็วสุด |
| `ig_submissions` | ~3 MB | ~5,000 | |
| `wheel_spins` | ~5 MB | ~15,000 | |
| `audit_logs` | ~10 MB | ~30,000 | |
| **รวม** | **< 100 MB** | | working set เข้า RAM ได้ทั้งหมดสบายๆ |

> ทั้ง dataset เล็กกว่า RAM มาก → Mongo จะอ่านจาก cache ทั้งหมด, ไม่มี disk I/O ในการอ่านเลย
> นี่คือเหตุผลที่ VPS 24GB เกินพอ และเป็นเหตุผลที่ไม่ต้อง sharding
