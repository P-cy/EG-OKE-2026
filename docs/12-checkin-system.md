# ระบบเช็คชื่อเข้างาน (Check-in) — EG'OKE 2026

เอกสารนี้อธิบายว่าระบบเช็คชื่อทำงานยังไง ใช้ API อะไรบ้าง และหน้างานต้องกดอะไร

---

## 1. หลักการ

| ข้อ | ค่าที่ใช้ |
|---|---|
| บัตร | **1 ใบต่อคน ใช้ได้ทั้งงาน** (ไม่ใช่ 1 ใบต่อวัน) |
| รหัสบัตร | `EGOKE26-XXXXXXXX` — ออกอัตโนมัติตอนผู้ใช้ทำ onboarding เสร็จ |
| วันที่ | **staff เลือกเองที่เครื่องสแกน (1/2/3)** ไม่ผูกกับปฏิทินจริง |
| กันสแกนซ้ำ | ต่อ "บัตร + วัน" — วันเดียวกันสแกนซ้ำ = `duplicate`, ข้ามวัน = `ok` |
| เหรียญ | `CHECKIN_COINS` (ตอนนี้ 10) ต่อวัน — มาครบ 3 วันได้ 3 ครั้ง |
| หลังเช็คอิน | มือถือผู้เข้างานเด้ง modal ผ่าน SSE + ลิงก์ Google Form (Attendance) |

**2 ด่านกันซ้ำ** (ต้องเข้าใจตอน debug):
1. Redis `ci:{ticket_id}:d{day}` — `SET NX` TTL 4 วัน = ด่านจริง เร็ว กัน race
2. Mongo `tickets.checked_in_days` — `$addToSet` แบบมีเงื่อนไข = ด่านสำรองถ้า Redis หาย

---

## 2. ผู้เข้างานทำอะไร

1. login Google → onboarding → **ระบบออกบัตรให้อัตโนมัติ**
2. เปิดหน้า `/ticket` → เห็น QR + รหัสบัตร
3. ยื่นให้ staff สแกน
4. มือถือเด้ง modal "เช็คอินสำเร็จ +10 coin วันที่ N" + ปุ่มไปกรอกฟอร์ม

---

## 3. staff เช็คชื่อได้ 4 ทาง

หน้า `/scan` (ต้องมี role `staff` หรือ `admin`)

| ทาง | ใส่อะไร | ใช้ตอนไหน |
|---|---|---|
| 1. กล้อง | สแกน QR | ปกติ — **ต้องเป็น https หรือ localhost** |
| 2. พิมพ์รหัสบัตร | `EGOKE26-1A2B3C4D` | กล้องไม่ติด / staff ใช้คอม |
| 3. พิมพ์รหัสนักศึกษา | `6913099` (7 หลัก) | มือถือผู้เข้างานแบตหมด |
| 4. QR payload เต็ม | `EGOKE2:1:EGOKE26-...:...:...` | copy จากหน้าบัตร |

หน้า `/admin/attendees` (role `admin`) — ค้นจากรายชื่อแล้วกดเช็คทีละคน + **กดยกเลิกได้ถ้าเช็คผิดวัน**

ทั้ง 4 ทางส่งเข้า field `payload` เดียวกัน — backend แยกเองว่าเป็นแบบไหน
(ทาง 2/3 ข้ามการตรวจ HMAC ได้เพราะ endpoint บังคับ role staff อยู่แล้ว — คนกดคือเจ้าหน้าที่)

---

## 4. API ทั้งหมดของระบบนี้

base URL: `http://localhost:8000/v1` (prod = โดเมนจริง)
ทุก endpoint ต้องมี `Authorization: Bearer <access_token>` ยกเว้นที่ระบุไว้

### ฝั่งผู้เข้างาน

| Method | Path | ทำอะไร |
|---|---|---|
| `GET` | `/me/tickets` | ดึงบัตรของตัวเอง — คืน array (มีใบเดียว) `{payload, ticket_code, status, checked_in_days[]}` |
| `GET` | `/me/stream?token=<jwt>` | **SSE** — push สดตอนถูกเช็คอิน (auth ผ่าน query เพราะ EventSource ส่ง header ไม่ได้) |
| `GET` | `/me/at-prompt` | ตอนเปิดแอป/login เช็คว่าควรเด้ง modal ฟอร์มไหม (เผื่อตอนสแกนปิดแอปอยู่) |
| `POST` | `/me/at-prompt/dismiss` | ปิด modal → ไม่เด้งซ้ำ 1 ชม. |

### ฝั่ง staff / admin

| Method | Path | Role | ทำอะไร |
|---|---|---|---|
| `POST` | `/checkin` | staff | **เช็คอิน 1 คน** ← ตัวหลัก |
| `POST` | `/checkin/batch` | staff | ส่งคิวที่ค้างตอนเน็ตหลุด (สูงสุด 100 รายการ) |
| `GET` | `/admin/attendees` | admin | รายชื่อ + สถานะรายวัน (`?q=&event_day=&status=checked\|unchecked`) |
| `POST` | `/admin/checkin/manual` | admin | เช็คชื่อจากรายชื่อ (ไม่ใช้ QR) |
| `POST` | `/admin/checkin/undo` | admin | **ยกเลิกเช็คอินของวันนั้น** (เลือกวันผิด) |
| `GET` | `/admin/dashboard` | admin | ยอดเช็คอินรวม |

### กิจกรรมบูธ (quests) — ใช้บัตรใบเดียวกัน

| Method | Path | Role | ทำอะไร |
|---|---|---|---|
| `GET` | `/quests` | ผู้ใช้ | กิจกรรมที่เปิด + ตัวเองรับไปแล้วกี่ครั้ง |
| `POST` | `/quests/claim` | staff | **แสตมป์ที่บูธ → จ่ายเหรียญ** (`{quest_key, payload, device_id}`) |
| `GET` | `/admin/quests` | admin | ทุกกิจกรรม + ยอดคนรับ |
| `POST` | `/admin/quests` | admin | เพิ่มกิจกรรม |
| `PATCH` | `/admin/quests/{key}` | admin | แก้ / เปิด-ปิด |
| `DELETE` | `/admin/quests/{key}` | admin | ลบ (ถ้ามีคนรับแล้วจะ **ปิดแทน** เพื่อไม่ให้ ledger อ้างของที่ไม่มี) |

`payload` ของ `/quests/claim` รับ 3 แบบเดียวกับ `/checkin` — staff ไม่ต้องเรียนรู้ใหม่
กันจ่ายซ้ำด้วย unique index `(quest_key, user_id, seq)` ไม่ใช่การนับก่อน insert
(นับก่อนคือ TOCTOU — สแกนรัวพร้อมกันจะจ่ายสองเด้ง)

### คุมรอบโหวต

| Method | Path | Role | ทำอะไร |
|---|---|---|---|
| `GET` | `/vote-rounds` | ผู้ใช้ | รอบทั้งหมด — **`status` คิดนาฬิกาแล้ว** (เลยเวลาปิด = `closed`) |
| `POST` | `/admin/vote-rounds/{key}/open` | admin | เปิดรับโหวต |
| `POST` | `/admin/vote-rounds/{key}/close` | admin | ปิด + freeze คะแนนเป็นผลทางการ |
| `POST` | `/admin/vote-rounds/{key}/publish` | admin | ประกาศผลให้ทุกคนเห็น |

หน้ากด: `/admin/rounds`

### `POST /v1/checkin` — รายละเอียด

```http
POST /v1/checkin
Authorization: Bearer <jwt ของ staff>
Idempotency-Key: <uuid>          # ไม่บังคับ แต่ควรส่ง
Content-Type: application/json

{
  "payload": "6913099",          # QR เต็ม | EGOKE26-XXXX | รหัส นศ. 7 หลัก
  "event_day": 1,                # 1-3 บังคับ
  "gate": "MAIN",                # ไม่บังคับ
  "device_id": "scanner-a1b2",   # บังคับ (ใช้ทำ rate limit 300/นาที ต่อเครื่อง)
  "scanned_at": "2026-08-07T10:00:00Z"   # ไม่บังคับ
}
```

ตอบกลับ 200 เสมอ (แม้ผลจะไม่ผ่าน) — ดูที่ `result`:

```json
{
  "result": "ok",
  "event_day": 1,
  "matched_by": "student_id",
  "message": "เข้างานวันที่ 1 เรียบร้อย",
  "user": { "display_name": "pp", "avatar_url": "...", "student_id": "6913099" },
  "ticket": { "ticket_code": "EGOKE26-1E4A5AEE", "checked_in_days": [1] },
  "coins_awarded": 10,
  "checked_in_at": "2026-08-07T03:20:00Z"
}
```

**ค่า `result` ที่เป็นไปได้**

| result | ความหมาย | staff ทำอะไร |
|---|---|---|
| `ok` | เช็คอินสำเร็จ | ให้ผ่าน |
| `duplicate` | วันนี้เช็คไปแล้ว | ให้ผ่าน (ไม่ต้องสแกนซ้ำ) |
| `not_found` | ไม่มีบัตรนี้ | ตรวจรหัสใหม่ / ค้นจากรายชื่อ |
| `no_ticket` | เจอคนแต่ยังไม่มีบัตร | ให้ไปทำ onboarding ก่อน |
| `invalid_sig` | อ่านรหัสไม่ออก / QR ปลอม | สแกนใหม่ / พิมพ์รหัส |
| `revoked` | บัตรถูกยกเลิก | ห้ามให้เข้า |
| `rotating_code_mismatch` | รหัสหมุนไม่ตรง (เฉพาะ STRICT_QR_MODE) | ให้เปิดหน้าบัตรจริง ไม่ใช่ภาพแคป |

`matched_by` = `qr` \| `ticket_code` \| `student_id` \| `manual` — บอกว่าจับคู่ได้จากอะไร

**Error จริง** (4xx/5xx) มาในรูปนี้เสมอ:
```json
{"error":{"code":"VALIDATION_ERROR","message":"...","request_id":"01KZ..."}}
```

---

## 5. ตั้งค่าที่เกี่ยวข้อง (`backend/.env`)

| ตัวแปร | ค่าปัจจุบัน | ผลถ้าเปลี่ยน |
|---|---|---|
| `CHECKIN_COINS` | `10` | เหรียญที่ได้ต่อการเช็คอิน 1 วัน |
| `STRICT_QR_MODE` | `false` | `true` = บังคับรหัสหมุน 6 หลัก (กันแคปหน้าจอ) — เปิดแล้วต้องมั่นใจว่านาฬิกาเครื่องสแกนตรง |
| `QR_SIGNING_KEY` | (ตั้งแล้ว) | **เปลี่ยนแล้ว QR เก่าทุกใบใช้ไม่ได้** |
| `ATTENDANCE_FORM_URL` | ลิงก์ Google Form | ว่าง = ซ่อนปุ่ม "ไปกรอกฟอร์ม" |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | ใส่หลายอันคั่นจุลภาคได้ — **ต้องใส่ LAN IP ถ้าจะทดสอบจากมือถือ** |

---

## 6. ข้อควรระวังหน้างาน

1. **กล้องต้องการ https หรือ localhost** — เปิดผ่าน `http://192.168.x.x:3000` กล้องจะไม่ทำงาน หน้า `/scan` จะขึ้นเตือนและซ่อนปุ่มเปิดกล้องให้ ใช้ช่องพิมพ์รหัสแทน
2. **ตรวจ "วันที่" ก่อนเริ่มสแกนทุกครั้ง** — หน้า `/scan` จำวันที่เลือกไว้ใน localStorage ของเครื่องนั้น ถ้าเลือกผิดแล้วสแกนไปแล้ว ใช้ `/admin/attendees` กดที่แถบวันสีเขียวเพื่อยกเลิก
3. **ยกเลิกเช็คอินไม่คืนเหรียญ** — เจตนา เพราะการเช็คอินซ้ำวันเดิมก็ไม่จ่ายซ้ำ (idempotency key `checkin:{code}:d{day}`) ยอดจึงตรงเสมอ
4. **ออฟไลน์** — เก็บคิวใน localStorage ของเครื่องนั้น แสดงผลเป็น "รอส่ง" (ไม่ใช่ "ผ่าน") เพราะยังไม่มีใครยืนยันว่าบัตรใช้ได้จริง กลับมาออนไลน์แล้วส่งอัตโนมัติ
5. **ทุกการสแกนถูกบันทึกใน `checkins`** รวมที่ถูกปฏิเสธ — ใช้พิสูจน์ตอนมีคนบ่นว่า "ผมสแกนแล้ว"

---

## 7. คำสั่ง debug ที่ใช้บ่อย

```bash
# ดูบัตรและวันที่เช็คไปแล้ว
docker compose exec -T mongo mongosh --quiet egoke2026 --eval \
  'db.tickets.find({},{ticket_code:1,checked_in_days:1,last_checked_in_at:1}).forEach(printjson)'

# ดูประวัติการสแกนล่าสุด (รวมที่ถูกปฏิเสธ)
docker compose exec -T mongo mongosh --quiet egoke2026 --eval \
  'db.checkins.find().sort({_id:-1}).limit(20).forEach(c=>print(c.result,c.ticket_code,"day="+c.event_day,c.source))'

# ล้างสถานะเช็คอินทั้งหมด (ทดสอบใหม่)
docker compose exec -T mongo mongosh --quiet egoke2026 --eval \
  'db.tickets.updateMany({},{$set:{checked_in_days:[],last_checked_in_at:null}}); db.checkins.deleteMany({}); db.coin_transactions.deleteMany({reason:"checkin"})'
docker compose exec -T redis redis-cli --scan --pattern 'ci:*' | xargs -r -n1 docker compose exec -T redis redis-cli DEL
```
