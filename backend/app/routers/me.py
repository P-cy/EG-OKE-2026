"""Profile, points history, tickets ของตัวเอง"""
import asyncio
import base64
import binascii
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core import ratelimit
from app.core.config import settings
from app.core.db import Col
from app.core.deps import CurrentUserDep, CurrentUserQueryDep, require_writable
from app.core.errors import AppError, not_found
from app.core.redis_client import K, get_redis
from app.core.security import build_qr_payload, totp_now
from app.models.schemas import AvatarUploadIn, ProfileUpdateIn, QROut, UserPublic
from app.realtime.notify_manager import notify_manager
from app.services.profile import missing_fields, needs_onboarding

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserPublic)
async def get_me(user: CurrentUserDep):
    doc = await Col.users().find_one({"_id": user.oid})
    if not doc:
        raise not_found("ผู้ใช้")

    rank = await get_redis().zrevrank(K.LB_COINS, user.id)
    return UserPublic(
        id=user.id,
        email=doc["email"],
        display_name=doc.get("display_name", ""),
        full_name=doc.get("full_name"),
        avatar_url=doc.get("avatar_url"),
        instagram_handle=doc.get("instagram_handle"),
        faculty=doc.get("faculty"),
        department=doc.get("department"),
        student_id=doc.get("student_id"),
        roles=doc.get("roles", []),
        coins_balance=doc.get("coins_balance", 0),
        rank=(rank + 1) if rank is not None else None,
        needs_onboarding=needs_onboarding(doc),
    )


@router.patch("", response_model=UserPublic)
async def update_me(body: ProfileUpdateIn, user: CurrentUserDep):
    updates: dict = {"updated_at": datetime.now(timezone.utc)}
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.instagram_handle is not None:
        updates["instagram_handle"] = body.instagram_handle.lower()
    if body.faculty is not None:
        updates["faculty"] = body.faculty.upper()
    if body.department is not None:
        updates["department"] = body.department.upper()
    if body.student_id is not None:
        updates["student_id"] = body.student_id
    if body.consent_photo is not None:
        updates["consent.photo"] = body.consent_photo
        updates["consent.tos"] = True
        updates["consent.at"] = datetime.now(timezone.utc)

    # ★ ต้องกรอกครบทุกช่องก่อนจบ onboarding
    #   เช็คก่อนเขียน ไม่ใช่หลัง — ถ้าเขียนไปแล้วค่อย reject จะได้ consent.tos=True
    #   ค้างไว้ในฐานข้อมูล แปลว่าคนนั้นผ่าน onboarding ไปทั้งที่ข้อมูลไม่ครบ
    #   และจะไม่มีอะไรพากลับมากรอกอีกเลย
    #
    #   ตรวจจาก "ค่าหลังรวมของใหม่" ไม่ใช่ค่าใน body อย่างเดียว — คนที่กรอกคณะ
    #   ไว้รอบก่อนแล้วรอบนี้ส่งมาแค่ consent ต้องผ่านได้
    current = await Col.users().find_one({"_id": user.oid})
    if not current:
        raise not_found("ผู้ใช้")

    if body.consent_photo is not None:
        merged = {**current, **{k.split(".")[0]: v for k, v in updates.items()}}
        missing = missing_fields(merged)
        if missing:
            raise AppError(
                400, "PROFILE_INCOMPLETE",
                f"ยังกรอกไม่ครบ — ขาด {' · '.join(missing)}",
                f"Profile incomplete: {', '.join(missing)}",
                details={"missing": missing},
            )

    doc = await Col.users().find_one_and_update(
        {"_id": user.oid}, {"$set": updates}, return_document=True
    )
    if not doc:
        raise not_found("ผู้ใช้")

    # ★ จบ onboarding (กดยอมรับ consent) → ออกบัตร QR ให้อัตโนมัติ (idempotent)
    #   1 ใบต่อ user ทั้งงาน — issue_ticket ใช้ unique index เป็นด่าน เรียกซ้ำไม่พัง
    if body.consent_photo is not None:
        from app.services.tickets import issue_ticket
        await issue_ticket(user.oid)

    # refresh meta cache ที่ leaderboard ใช้
    await get_redis().set(
        K.USER_META.format(uid=user.id),
        json.dumps({
            "display_name": doc.get("display_name"),
            "avatar_url": doc.get("avatar_url"),
            "instagram_handle": doc.get("instagram_handle"),
        }),
        ex=3600,
    )
    return await get_me(user)


# ── Avatar ─────────────────────────────────────────────────────────────
# magic bytes ของรูปแต่ละชนิด — ใช้ดัดจารึกและกันคนส่ง payload อย่างอื่นมาแอบอ้าง
_IMG_SIGNATURES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/webp": b"RIFF",  # 4 ไบต์แรก ส่วน "WEBP" อยู่ที่ offset 8
}


@router.post("/avatar", response_model=UserPublic, dependencies=[Depends(require_writable)])
async def upload_avatar(body: AvatarUploadIn, user: CurrentUserDep):
    await ratelimit.check("avatar", user.id)

    # ถอด base64 ดูจริง — กันคนส่งขยะมาเก็บใน Mongo
    try:
        raw = base64.b64decode(body.image_data, validate=True)
    except (binascii.Error, ValueError):
        raise AppError(400, "INVALID_IMAGE", "รูปไม่ถูกต้อง", "Invalid base64 image data")
    if len(raw) < 200:
        raise AppError(400, "INVALID_IMAGE", "รูปไม่ถูกต้อง", "Image too small")
    if len(raw) > 512 * 1024:
        raise AppError(
            400, "IMAGE_TOO_LARGE",
            "รูปใหญ่เกินไป กรุณาเลือกรูปเล็กกว่า 512KB",
            "Image exceeds 512KB",
        )

    # ตรวจ magic bytes ตรงกับ mime ที่อ้าง
    sig = _IMG_SIGNATURES.get(body.mime)
    if not sig or not raw.startswith(sig):
        # WEBP: RIFF....WEBP
        if body.mime == "image/webp" and not (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"):
            raise AppError(400, "INVALID_IMAGE", "ไฟล์ไม่ตรงชนิดรูปที่ระบุ", "Image signature mismatch")
        elif body.mime != "image/webp":
            raise AppError(400, "INVALID_IMAGE", "ไฟล์ไม่ตรงชนิดรูปที่ระบุ", "Image signature mismatch")

    now = datetime.now(timezone.utc)
    version = int(now.timestamp())
    avatar_url = f"{settings.API_BASE_URL}/v1/avatars/{user.id}?v={version}"

    doc = await Col.users().find_one_and_update(
        {"_id": user.oid},
        {"$set": {
            "avatar_data": body.image_data,
            "avatar_mime": body.mime,
            "avatar_updated_at": now,
            "avatar_url": avatar_url,
            "updated_at": now,
        }},
        return_document=True,
    )
    if not doc:
        raise not_found("ผู้ใช้")

    # invalidate meta cache ที่ leaderboard ใช้ — สำคัญมาก ไม่งั้นหน้าจอยังเห็นรูปเก่า
    await get_redis().set(
        K.USER_META.format(uid=user.id),
        json.dumps({
            "display_name": doc.get("display_name"),
            "avatar_url": avatar_url,
            "instagram_handle": doc.get("instagram_handle"),
        }),
        ex=3600,
    )
    return await get_me(user)


@router.get("/points")
async def my_points(user: CurrentUserDep, limit: int = 50, cursor: str | None = None):
    """ledger ของตัวเอง — cursor-based pagination (ห้ามใช้ skip)"""
    q: dict = {"user_id": user.oid}
    if cursor:
        from bson import ObjectId
        q["_id"] = {"$lt": ObjectId(cursor)}

    rows = await Col.coin_transactions().find(q).sort("_id", -1).to_list(min(limit, 100))
    return {
        "balance": await _balance(user.oid),
        "items": [
            {
                "id": str(t["_id"]),
                "amount": t["amount"],
                "balance_after": t.get("balance_after"),
                "reason": t["reason"],
                "note": t.get("note", ""),
                "created_at": t["created_at"],
            }
            for t in rows
        ],
        "next_cursor": str(rows[-1]["_id"]) if len(rows) == min(limit, 100) else None,
    }


@router.get("/tickets", response_model=list[QROut])
async def my_tickets(user: CurrentUserDep):
    """บัตรของ user (1 ใบทั้งงาน) + QR payload + rotating code

    rotating code เปลี่ยนทุก 30 วิ → แคปหน้าจอส่งให้เพื่อนใช้ไม่ได้นาน
    """
    tickets = await Col.tickets().find({"user_id": user.oid}).sort("issued_at", 1).to_list(10)
    now = int(time.time())
    # ★ รหัสหมุนโชว์เฉพาะตอน STRICT_QR_MODE เปิด — ไม่งั้นเป็นตัวเลขหลอกตา
    #   (ระบบไม่ได้ตรวจ แต่ผู้ใช้เห็นแล้วนึกว่าต้องใช้)
    strict = settings.STRICT_QR_MODE and bool(settings.TOTP_KEY)
    return [
        QROut(
            # ★ ผูก issued_ts กับ issued_at ของบัตร → payload คงที่ตลอด
            #   ถ้าใช้ time.time() QR จะเปลี่ยนทุกครั้งที่ poll (ทุก 5 วิ) กล้องจับยาก
            #   และ cache offline ใน localStorage ก็ไม่ตรงกับที่แสดงอยู่
            payload=build_qr_payload(t["ticket_code"], _issued_ts(t)),
            ticket_code=t["ticket_code"],
            event_day=0,            # single whole-event ticket (legacy field, 0 = no day)
            status=t["status"],
            checked_in_days=sorted(t.get("checked_in_days", [])),
            rotating_code=totp_now(t["ticket_code"]) if strict else None,
            rotates_in=(settings.TOTP_PERIOD - (now % settings.TOTP_PERIOD)) if strict else None,
        )
        for t in tickets
    ]


def _issued_ts(ticket: dict) -> int:
    issued = ticket.get("issued_at") or ticket.get("created_at")
    if not issued:
        return 0
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
    return int(issued.timestamp())


@router.get("/submissions")
async def my_submissions(user: CurrentUserDep):
    """คำขอขึ้นจอของตัวเอง

    ★ คีย์ต้องเป็น "items" — ของเดิมคืน "submissions" แต่หน้า /ig อ่าน `data.items`
      ผลคือกล่อง "สถานะคำขอของคุณ" ขึ้นว่า "ยังไม่เคยส่ง" ตลอด แม้จะส่งไปแล้ว
    ★ ต้องมี instagram_handle / caption ของ "ใบนั้น" ด้วย ไม่งั้นหน้าเว็บ
      ต้องเดาจากช่องกรอกที่ยังแก้ค้างอยู่ → ทุกแถวโชว์ชื่อเดียวกันหมด
    """
    rows = await Col.ig_submissions().find(
        {"user_id": user.oid},
        {"image_data": 0},          # ★ ไม่ต้องส่ง base64 กลับมา ผู้ใช้เห็นรูปตัวเองอยู่แล้ว
    ).sort("_id", -1).to_list(50)
    return {
        "items": [
            {
                "id": str(s["_id"]),
                "shortcode": s["shortcode"],
                "status": s["status"],
                "instagram_handle": s.get("instagram_handle"),
                "caption": s.get("caption", ""),
                "coins_awarded": s.get("coins_awarded", 0),
                "reject_reason": s.get("reject_reason"),
                "submitted_at": s["submitted_at"],
                "reviewed_at": s.get("reviewed_at"),
            }
            for s in rows
        ]
    }


@router.get("/export")
async def export_my_data(user: CurrentUserDep):
    """PDPA: สิทธิเข้าถึงข้อมูลของตัวเอง"""
    doc = await Col.users().find_one({"_id": user.oid}) or {}
    doc.pop("_id", None)
    doc.pop("google_sub", None)
    return {
        "profile": json.loads(json.dumps(doc, default=str)),
        "points": [
            json.loads(json.dumps({k: v for k, v in t.items() if k != "_id"}, default=str))
            async for t in Col.coin_transactions().find({"user_id": user.oid})
        ],
        "votes": [
            json.loads(json.dumps({k: v for k, v in v_.items() if k != "_id"}, default=str))
            async for v_ in Col.votes().find({"user_id": user.oid})
        ],
        "exported_at": datetime.now(timezone.utc),
    }


# ── Attendance prompt + SSE push (เด้ง modal เวลาถูกเช็คอิน) ────────────
@router.get("/at-prompt")
async def at_prompt(user: CurrentUserDep):
    """เช็คว่าควรเด้ง modal ฟอร์ม Attendance หรือไม่ (หลัง login/reopen แอป)

    อ่าน ticket จาก Mongo (durable) — ถ้าเพิ่งเช็คอินภายใน 6h ให้ show
    ถ้าปิดไปแล้ว (AT_DISMISSED TTL 1h) ไม่ show (ครอบเฉพาะ path login re-show
    ไม่ห้าม live push จาก SSE)
    """
    r = get_redis()
    if await r.exists(K.AT_DISMISSED.format(uid=user.id)):
        return {"show": False, "dismissed": True}

    ticket = await Col.tickets().find_one(
        {"user_id": user.oid},
        {"checked_in_days": 1, "last_checked_in_at": 1},
    )
    if not ticket:
        return {"show": False}

    last = ticket.get("last_checked_in_at")
    days = ticket.get("checked_in_days", [])
    if not last or not days:
        return {"show": False}

    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if (now - last).total_seconds() > 6 * 3600:
        return {"show": False}

    return {
        "show": True,
        "event_day": max(days),
        "coins_awarded": settings.CHECKIN_COINS,
        "form_url": settings.ATTENDANCE_FORM_URL,
        "checked_in_at": last.isoformat(),
    }


@router.post("/at-prompt/dismiss")
async def at_prompt_dismiss(user: CurrentUserDep):
    """ปิด modal → suppress login re-show 1h (live push ยังทำงานได้)"""
    await get_redis().set(K.AT_DISMISSED.format(uid=user.id), "1", ex=3600)
    return {"ok": True}


@router.get("/stream")
async def me_stream(user: CurrentUserQueryDep):
    """SSE — push สดไปมือถือคนเข้างานเวลาถูกสแกนเช็คอิน

    auth ด้วย ?token=<jwt> (EventSource ส่ง header ไม่ได้)
    ส่ง: retry: 5000 (กัน reconnect storm) → replay notify:last ถ้ามี → รับจาก queue
    heartbeat : ping ทุก ~25s กัน proxy ตัด

    ★ ใช้ notify_manager singleton (1 Redis connection ตลอด ไม่ว่าจะมีกี่คนเปิด SSE)
      แต่ละ SSE แค่อ่าน queue ของตัวเอง — รองรับ 500+ คนเปิดแอปพร้อมกัน
    """
    r = get_redis()
    uid = user.id
    last_key = K.NOTIFY_LAST.format(uid=uid)

    async def gen():
        # บอก client ว่าถ้าหลุดให้ reconnect ใน 5 วิ (ไม่ใช่ทันที → กัน storm)
        yield "retry: 5000\n\n"
        # reattach: replay last payload ถ้ามี (กรณีตอนสแกนมือถือปิดอยู่)
        last = await r.get(last_key)
        if last:
            yield f"event: checkin_ok\ndata: {last}\n\n"

        sub = notify_manager.subscribe(uid)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(sub.queue.get(), timeout=25.0)
                    yield f"event: checkin_ok\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    # ไม่มีข้อความ 25s → heartbeat (SSE comment, client ไม่สน)
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass  # client ปิดการเชื่อมต่อ
        finally:
            notify_manager.unsubscribe(uid, sub)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",   # ปิด Nginx buffering
            "Connection": "keep-alive",
        },
    )


async def _balance(oid) -> int:
    doc = await Col.users().find_one({"_id": oid}, {"coins_balance": 1})
    return (doc or {}).get("coins_balance", 0)
