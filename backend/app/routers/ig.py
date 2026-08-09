"""Instagram submission + moderation queue

ระบบจอใหญ่: ผู้ใช้จ่ายเหรียญ → อัปโหลดรูป + ชื่อ IG + แคปชัน
            → เข้าคิวรอ admin อนุมัติ → ขึ้นจอใหญ่หน้างาน
"""
import base64
import binascii
import re
import uuid
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, Request, Response
from pymongo.errors import DuplicateKeyError

from app.core import ratelimit
from app.core.db import Col
from app.core.deps import CurrentUserDep, require_feature, require_writable
from app.core.errors import AppError, conflict, not_found
from app.models.schemas import IGSubmitIn
from app.services import coins

router = APIRouter(prefix="/ig", tags=["instagram"])

# จอใหญ่: ค่าใช้จ่ายเหรียญต่อครั้ง
WALL_COST = 20
# รูป base64 เก็บใน doc
# ★ ลดจาก 4MB → 1.4MB (~1MB จริง): frontend ย่อรูปให้เหลือด้านยาว 1440px ก่อนส่งอยู่แล้ว
#   ค่าเดิมเปิดช่องให้ client ที่ไม่ย่อ ยัดรูป 3MB เข้ามา แล้วจอใหญ่ต้องโหลดทั้งกอง
IMAGE_MAX = 1_400_000

# ชื่อ IG ต้องเป็นตัวอักษร/ตัวเลข/._ เท่านั้น
HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


@router.post(
    "/submissions",
    status_code=201,
    dependencies=[Depends(require_feature("ig_submission", "ส่งโพสต์ Instagram")),
                  Depends(require_writable)],
)
async def submit(body: IGSubmitIn, user: CurrentUserDep):
    """ส่งรูปขึ้นจอใหญ่ — จ่ายเหรียญก่อน"""
    await ratelimit.check("ig", user.id)

    # ★ เปลี่ยนจาก post_url เป็น image_data + handle + caption (ระบบจอใหญ่)
    image_data = getattr(body, "image_data", None)
    instagram_handle = getattr(body, "instagram_handle", None) or ""

    if not image_data or len(image_data) < 100:
        raise AppError(400, "NO_IMAGE", "กรุณาเลือกรูปก่อน", "Image required")
    if len(image_data) > IMAGE_MAX:
        raise AppError(400, "IMAGE_TOO_LARGE", "รูปใหญ่เกินไป กรุณาลองรูปอื่น",
                       f"Image exceeds {IMAGE_MAX} base64 chars")
    handle = instagram_handle.strip().lstrip("@")
    if not HANDLE_RE.match(handle):
        raise AppError(400, "INVALID_HANDLE", "ชื่อ IG ไม่ถูกต้อง", "Invalid IG handle")

    caption = (getattr(body, "caption", None) or "").strip()[:200]
    now = datetime.now(timezone.utc)
    shortcode = f"local:{uuid.uuid4().hex}"  # id ภายใน (schema เดิมใช้ shortcode เป็น unique key)

    # ★ หักเหรียญแบบ atomic — เช็คยอดกับหักเป็น operation เดียว
    #   ของเดิมเช็ค balance แล้วค่อยหัก = กดรัวสองครั้งผ่านทั้งคู่ ยอดติดลบได้
    spent = await coins.spend(
        user_id=user.oid, amount=WALL_COST, reason="ig_wall",
        idempotency_key=f"ig_wall_cost:{shortcode}",
        ref={"type": "ig_submission"},
        note=f"ส่งรูปขึ้นจอ IG (@{handle})",
    )
    if spent.insufficient:
        raise AppError(
            402, "INSUFFICIENT_COINS",
            f"เหรียญไม่พอ ต้องมีอย่างน้อย {WALL_COST} เหรียญ",
            "Insufficient coins",
            details={"required": WALL_COST, "balance": spent.balance},
        )

    try:
        res = await Col.ig_submissions().insert_one({
            "user_id": user.oid,
            "shortcode": shortcode,
            "post_url": "",
            "instagram_handle": handle,
            "caption": caption,
            "image_data": image_data,         # base64 รูป
            "status": "pending",
            "coins_awarded": 0,
            "auto_flags": [],
            "submitted_at": now,
            "schema_version": 2,
        })
    except DuplicateKeyError:
        # ไม่น่าเกิดเพราะ shortcode เป็น uuid สุ่ม แต่กันไว้
        raise conflict("SUBMISSION_EXISTS", "ส่งซ้ำ")

    queue_pos = await Col.ig_submissions().count_documents(
        {"status": "pending", "submitted_at": {"$lt": now}}
    )
    return {
        "id": str(res.inserted_id),
        "status": "pending",
        "queue_position": queue_pos + 1,
        "coins_spent": WALL_COST,
        "new_balance": spent.balance,
    }


@router.get("/config")
async def ig_config():
    """ค่าคงที่ของระบบส่งรูปขึ้นจอ

    ★ มีไว้เพื่อไม่ให้ frontend hardcode ราคาเอง — ของเดิมเขียน WALL_COST = 20
      ไว้ทั้งสองฝั่ง วันไหนเปลี่ยนราคาที่ backend หน้าเว็บจะโชว์ราคาเก่า
      แล้วผู้ใช้กดส่งไปโดนหักคนละราคากับที่เห็น
    """
    return {
        "cost_coins": WALL_COST,
        "image_max_bytes": IMAGE_MAX,
        "caption_max": 200,
        "handle_pattern": HANDLE_RE.pattern,
    }


@router.get("/image/{submission_id}")
async def ig_image(submission_id: str, request: Request):
    """รูปของโพสต์ที่อนุมัติแล้ว — public, cache ยาว

    ★ ทำไมต้องมี: /live/ig-wall เคยยัด base64 ของทุกใบมาในก้อน JSON
      จอใหญ่ poll ทุก 10 วิ × 30 ใบ = โหลดรูปทั้งกองใหม่ทุก 10 วิ ตลอดงาน
      แยกเป็น URL แล้ว browser cache ได้ (id ไม่เปลี่ยน = เนื้อหาไม่เปลี่ยน)
      → หลังรอบแรก จอแทบไม่ใช้ bandwidth เลย
    """
    await ratelimit.check_public("live", request)

    if not ObjectId.is_valid(submission_id):
        raise not_found("รูป")

    doc = await Col.ig_submissions().find_one(
        {"_id": ObjectId(submission_id), "status": "approved"},
        {"image_data": 1},
    )
    if not doc or not doc.get("image_data"):
        raise not_found("รูป")

    raw = doc["image_data"]
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        img = base64.b64decode(raw)
    except (binascii.Error, ValueError):
        raise not_found("รูป")

    # ★ ต้องใส่ header ที่ Response ที่ return จริง — ถ้าไปเซ็ตที่ `response: Response`
    #   ที่ inject เข้ามา มันจะถูกทิ้งทั้งก้อนเมื่อเรา return Response ใหม่
    #   (จุดนี้พลาดง่ายมาก และผลคือ cache ไม่ทำงานเลยทั้งที่โค้ดดูเหมือนตั้งไว้แล้ว)
    return Response(
        content=img,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )
