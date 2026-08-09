"""ออกบัตร QR — 1 ใบต่อ user ทั้งงาน (idempotent ผ่าน unique index บน user_id)"""
from datetime import datetime, timezone

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.db import Col
from app.core.observability import log
from app.core.redis_client import K, get_redis
from app.core.security import new_ticket_code

EVENT_DAYS = (1, 2, 3)


async def issue_ticket(user_id: ObjectId) -> dict | None:
    """สร้างบัตรให้ user ถ้ายังไม่มี — คืน ticket doc หรือ None ถ้ามีอยู่แล้ว

    idempotent: unique index `uq_user` บน `user_id` เป็นด่าน เรียกซ้ำไม่สร้างใหม่
    """
    now = datetime.now(timezone.utc)
    code = new_ticket_code()
    try:
        await Col.tickets().insert_one({
            "ticket_code": code,
            "user_id": user_id,
            "status": "issued",        # ไม่ flip เป็น checked_in เพราะใช้บัตรเดียวกันข้ามวัน
            "tier": "general",
            "qr_version": settings.QR_VERSION,
            "checked_in_days": [],      # [1] → [1,2] → [1,2,3] ตามที่สแกนแต่ละวัน
            "last_checked_in_at": None,
            "last_checked_in_by": None,
            "last_checked_in_gate": None,
            "issued_at": now,
            "created_at": now,
            "schema_version": 2,        # ใหม่: ไม่มี event_day, มี checked_in_days
        })
        log.info("ticket_issued", user_id=str(user_id), ticket_code=code)
        return await Col.tickets().find_one({"ticket_code": code})
    except DuplicateKeyError:
        return None  # มีบัตรอยู่แล้ว — ปกติ ไม่ใช่ error


async def has_checked_in(user_id: ObjectId) -> bool:
    """เคยเช็คอินวันไหนก็ได้ในงานนี้หรือยัง

    ★ ใช้กับกติกา REQUIRE_CHECKIN_TO_VOTE
      ของเดิม votes.py อ่าน set ชื่อ `checked_in:today` ซึ่ง **ไม่มีโค้ดไหนเขียนเลย**
      → เปิดกติกานี้เมื่อไหร่ ทุกคนโหวตไม่ได้ทั้งงาน
      ตอนนี้อ่าน `checked_in:day{1,2,3}` ที่ checkin_core เขียนจริง
      แล้ว fallback ไป Mongo เผื่อ Redis เคยถูกล้าง (ข้อมูลจริงอยู่ที่ Mongo)
    """
    uid = str(user_id)
    try:
        r = get_redis()
        pipe = r.pipeline()
        for day in EVENT_DAYS:
            pipe.sismember(K.CHECKIN_DAY_SET.format(day=day), uid)
        if any(await pipe.execute()):
            return True
    except Exception:
        log.warning("checkin_set_read_failed", user_id=uid)

    # Redis ไม่มี → ถามแหล่งข้อมูลจริง
    ticket = await Col.tickets().find_one({"user_id": user_id}, {"checked_in_days": 1})
    return bool((ticket or {}).get("checked_in_days"))
