# 10 — IG Wall Feature (จ่ายคะแนนเพื่อขึ้นจอใหญ่)

> คุณสมบัติใหม่ที่ frontend ทำไว้แล้ว แต่ backend ต้องเพิ่มให้ครบ
> ผู้ใช้จ่ายคะแนน → แปะรูป + ชื่อ IG → รอ Admin อนุมัติ → ขึ้นจอใหญ่หน้างาน

## สรุป flow

```
ผู้ใช้:
  เลือกรูป (≤4MB) → ใส่ชื่อ IG → กดส่ง
    │
    ▼
Backend:
  POST /ig/submissions  (★ เปลี่ยนจากเดิม)
    1. ตรวจคะแนนเพียงพอ (≥ WALL_COST)
    2. หักคะแนนทันทีผ่าน ledger (reason = "ig_wall")
    3. เก็บรูป (base64 หรือ object storage key)
    4. สร้าง submission status=pending
    │
    ▼
Admin:
  /admin/ig → เห็นรูป + "IG: @ชื่อ" → อนุมัติ/ปฏิเสธ
    │
    ▼
Backend:
  POST /admin/ig/{id}/approve
    - status=approved
    - เพิ่มเข้าคิวจอใหญ่ (Redis list หรือ collection ใหม่)
    │
    ▼
Display:
  /display/ig → ดึง approved submissions → แสดงรูป + "IG: @ชื่อ"
```

## 1. ฟิลด์ที่ต้องเพิ่มใน collection `ig_submissions`

เดิมเก็บแค่ shortcode + post_url ตอนนี้ต้องเก็บรูป + IG handle ที่ผู้ใช้ใส่เอง:

```jsonc
{
  "_id": ObjectId,
  "user_id": ObjectId,
  "shortcode": "CxYz123ABC",            // ยังเก็บถ้าส่ง URL มา (optional แล้ว)
  "post_url": "...",                     // optional แล้ว
  "image_data": "<base64>",              // ★ ใหม่ — รูปที่ผู้ใช้อัปโหลด
  "image_storage_key": "ig/2026/xxx.webp", // ★ ถ้าย้ายไป object storage
  "instagram_handle": "pp_egoke",       // ★ ใหม่ — ชื่อ IG ที่ผู้ใช้ใส่ (แสดงบนจอ)
  "caption": "...",                      // ★ ใหม่ — ข้อความใต้รูป
  "status": "pending",                   // pending|approved|rejected|flagged
  "points_spent": 20,                    // ★ ใหม่ — คะแนนที่หักตอนส่ง
  "points_awarded": 0,                   // ถ้ามีโบนัสด้วย
  "wall_shown_at": ISODate,              // ★ ใหม่ — วันที่ขึ้นจอ
  "wall_position": null,                // ★ ใหม่ — ลำดับบนจอ (ถ้ามี)
  "reviewed_by": ObjectId,
  "reviewed_at": ISODate,
  "reject_reason": null,
  "auto_flags": [],
  "submitted_at": ISODate,
  "schema_version": 2                    // bump
}
```

**Indexes ที่ต้องเพิ่ม:**
```js
db.ig_submissions.createIndex({ status: 1, submitted_at: 1 })   // มีอยู่แล้ว — คิว moderation
db.ig_submissions.createIndex({ status: 1, wall_shown_at: -1 }) // ★ ใหม่ — ดึงของที่จะขึ้นจอ
```

## 2. Config ที่ต้องเพิ่ม (ใน `system_config` หรือ env)

```jsonc
{
  "ig_wall_cost": 20,                    // คะแนนที่หักต่อครั้ง
  "ig_wall_max_pending_per_user": 3,     // กันสแปม — คิวรอตรวจไม่เกิน 3
  "ig_wall_auto_approve": false,         // true = ข้าม admin (ใช้เฉพาะทดสอบ)
  "ig_wall_max_image_bytes": 4194304      // 4MB
}
```

เพิ่มใน `config.py`:
```python
IG_WALL_COST: int = 20
IG_WALL_MAX_PENDING_PER_USER: int = 3
IG_WALL_MAX_IMAGE_BYTES: int = 4_194_304
```

## 3. Endpoints ที่ต้องแก้/เพิ่ม

### 3.1 แก้ `POST /ig/submissions` (มีอยู่แล้วใน `routers/ig.py`)

เดิมรับ `post_url` อย่างเดียว ต้องเปลี่ยนเป็นรูป + IG handle:

```python
class IGSubmitIn(BaseModel):
    image_data: str = Field(min_length=100)  # base64
    instagram_handle: str = Field(pattern=r"^[A-Za-z0-9._]{1,30}$")
    caption: str | None = Field(None, max_length=200)
    post_url: HttpUrl | None = None  # optional ถ้าอยากแปะลิงก์ด้วย
```

ใน router:
```python
# 1. ตรวจขนาดรูป
if len(body.image_data) > settings.IG_WALL_MAX_IMAGE_BYTES:
    raise AppError(413, "IMAGE_TOO_LARGE", "รูปใหญ่เกิน 4MB")

# 2. ตรวจคะแนนเพียงพอ
balance = await points.balance_of(user.oid)
if balance < settings.IG_WALL_COST:
    raise AppError(402, "INSUFFICIENT_POINTS",
        f"ต้องมีคะแนนอย่างน้อย {settings.IG_WALL_COST}")

# 3. ตรวจคิวที่ค้างอยู่ (กันสแปม)
pending = await Col.ig_submissions().count_documents(
    {"user_id": user.oid, "status": "pending"}
)
if pending >= settings.IG_WALL_MAX_PENDING_PER_USER:
    raise AppError(409, "TOO_MANY_PENDING",
        f"คุณมีคำขอรอตรวจ {pending} รายการ รออนุมัติก่อน")

# 4. ★ หักคะแนนก่อน (idempotent) — เหตุผล "ig_wall"
res = await points.award(
    user_id=user.oid, amount=-settings.IG_WALL_COST,
    reason="ig_wall", idempotency_key=f"ig_wall:{user.id}:{idempotency_key}",
    actor_id=user.oid, note="จ่ายค่าขึ้นจอ IG",
)
if not res.awarded:
    # ซ้ำ → ไม่หักซ้ำ แต่ถือว่าส่งแล้ว
    pass

# 5. เก็บ submission
doc = {
    "user_id": user.oid,
    "image_data": body.image_data,  # หรืออัปโหลดไป storage แล้วเก็บ key
    "instagram_handle": body.instagram_handle,
    "caption": body.caption,
    "status": "pending",
    "points_spent": settings.IG_WALL_COST,
    "submitted_at": now,
    "schema_version": 2,
}
```

### 3.2 แก้ `GET /admin/ig/queue` (มีอยู่แล้วใน `routers/admin.py`)

เพิ่ม field ใน response:
```python
# ใน items list
{
    "id": str(r["_id"]),
    "image_data": r.get("image_data"),          # ★ ส่งกลับให้ admin เห็นรูป
    "instagram_handle_display": r.get("instagram_handle"),  # ★
    "caption": r.get("caption"),                 # ★
    "status": r["status"],
    "submitted_at": r["submitted_at"],
    "auto_flags": r.get("auto_flags", []),
    "user": { ... },
}
```

### 3.3 แก้ `POST /admin/ig/{id}/approve` (มีอยู่แล้ว)

ตอนอนุมัติ ให้ตั้ง `wall_shown_at` หรือเพิ่มเข้าคิวจอ:
```python
await Col.ig_submissions().update_one(
    {"_id": sub["_id"]},
    {"$set": {
        "status": "approved",
        "reviewed_by": admin.oid,
        "reviewed_at": datetime.now(timezone.utc),
        "wall_shown_at": datetime.now(timezone.utc),  # ★
    }},
)
# ถ้ามีรางวัลคะแนนด้วย ให้ + ที่นี่ (optional)
# ถ้าไม่มี — คะแนนที่หักตอนส่งถือว่าจ่ายแล้ว ไม่คืน
```

### 3.4 ★ ใหม่: `GET /live/ig-wall` — สำหรับจอใหญ่

```python
@router.get("/live/ig-wall")
async def ig_wall(limit: int = 20):
    """ดึง approved submissions ล่าสุดสำหรับจอใหญ่ — cache 5 วิ"""
    rows = await Col.ig_submissions().find(
        {"status": "approved", "image_data": {"$exists": True}}
    ).sort("wall_shown_at", -1).to_list(min(limit, 50))
    return {
        "items": [
            {
                "id": str(r["_id"]),
                "image_data": r["image_data"],
                "instagram_handle": r.get("instagram_handle"),
                "caption": r.get("caption"),
                "display_name": (await Col.users().find_one(
                    {"_id": r["user_id"]}, {"display_name": 1}
                )).get("display_name") if r.get("user_id") else None,
                "shown_at": r.get("wall_shown_at"),
            }
            for r in rows
        ],
        "as_of": datetime.now(timezone.utc),
    }
```

> ควร cache ใน Redis (`live:ig-wall` TTL 5s) เหมือน snapshot อื่น
> ถ้ารูปใหญ่ ควรย้ายไป object storage (S3/MinIO/Cloudflare R2) แล้วคืน URL แทน base64

## 4. สิ่งที่ frontend ทำไว้แล้ว (อ้างอิง)

| หน้า | ไฟล์ | สถานะ |
|---|---|---|
| ส่งรูป + IG handle | `src/app/ig/page.tsx` | ส่ง `{image_data, instagram_handle, caption}` |
| คิว Admin (เห็นรูป + อนุมัติ/ปฏิเสธ) | `src/app/admin/ig/page.tsx` | แสดง `image_data` และ `igLabel(handle)` |
| จอใหญ่ | `src/app/display/ig/page.tsx` | ★ ตอนนี้ใช้ leaderboard placeholder — ต้องเปลี่ยนเป็นเรียก `GET /live/ig-wall` |
| ประวัติคะแนน | `src/app/points/page.tsx` | แสดง reason `ig_wall` เป็น "ขึ้นจอ IG" |

## 5. Checklist สำหรับ backend team

- [ ] bump `schema_version` ของ `ig_submissions` เป็น 2
- [ ] เพิ่ม field `image_data`, `instagram_handle`, `caption`, `points_spent`, `wall_shown_at`
- [ ] เพิ่ม index `{status: 1, wall_shown_at: -1}`
- [ ] แก้ `IGSubmitIn` ใน `schemas.py` ให้รับ `image_data` + `instagram_handle`
- [ ] แก้ `POST /ig/submissions` ใน `routers/ig.py`: หักคะแนน + เก็บรูป
- [ ] เพิ่ม config `IG_WALL_COST` ฯลฯ ใน `config.py`
- [ ] แก้ `GET /admin/ig/queue` ให้คืน `image_data` + `instagram_handle_display`
- [ ] แก้ `POST /admin/ig/{id}/approve` ให้ตั้ง `wall_shown_at`
- [ ] เพิ่ม `GET /live/ig-wall` + cache ใน Redis
- [ ] แก้ `frontend/src/lib/api.ts` เพิ่ม `getIGWall()` แล้วเรียกใน `display/ig/page.tsx`
- [ ] พิจารณาย้ายรูปไป object storage ถ้ารูปใหญ่/เยอะ (base64 พอง collection)

## 6. ข้อควรระวัง

- **รูป base64 ทำให้ doc ใหญ่ขึ้นมาก** — 4MB base64 ≈ 5.3MB ต่อ doc ถ้ามี 1,000 รายการ = 5GB
  แนะนำ: อัปโหลดไป Cloudflare R2 (ฟรี 10GB) แล้วเก็บแค่ URL/key
- **PDPA**: รูปคือข้อมูลส่วนบุคคล ต้องมี consent + ลบได้ตามคำขอ → เก็บ `consent_photo` ใน user ไว้แล้ว
- **Moderation**: ถ้าคิวยาว ผู้ใช้รอนาน → ตั้ง expectation ชัดๆ ในหน้าส่ง ("อนุมัติใน X นาที")
- **คืนคะแนน**: ถ้า admin ปฏิเสธ จะคืนคะแนนหรือไม่? (แนะนำ: ไม่คืน เพราะ "จ่ายเพื่อส่ง" ไม่ใช่ "จ่ายเพื่อผ่าน")
