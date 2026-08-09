"""Staff API — สิทธิ์เท่าที่คนอยู่หน้างานต้องใช้ ไม่มากกว่านั้น

staff ทำได้ 3 อย่าง:
  1. สแกนเช็คอิน            → POST /checkin (อยู่ใน routers/checkin.py)
  2. สแกนจ่ายเหรียญที่บูธ    → POST /staff/coins/grant (ที่นี่)
  3. ค้นรายชื่อ + เช็คชื่อด้วยมือ → ที่นี่

★ ที่ไม่ให้ staff ทำ: ยกเลิกเช็คอิน · ปรับเหรียญด้วยมือ · ตั้ง role · แก้ config ·
  อนุมัติ IG · เปิด-ปิดรอบโหวต · ดู audit log · ดาวน์โหลดข้อมูล
  งานนี้ staff เป็นนักศึกษาอาสาหลายสิบคน แจก role ให้กว้างแล้วถอนคืนไม่ได้
"""
import json
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, Header, Request

from app.core import ratelimit
from app.core.db import Col
from app.core.deps import CurrentUser, require_feature, require_staff, require_writable
from app.core.errors import not_found
from app.core.observability import log
from app.core.redis_client import K, get_redis
from app.models.schemas import CheckinOut, CoinGrantIn, CoinGrantOut, ManualCheckinIn
from app.routers.checkin import REASON_MESSAGE, checkin_core, resolve_ticket
from app.services import coins, grant_limits
from app.services.attendance import query_attendees
from app.services.audit import audit

router = APIRouter(prefix="/staff", tags=["staff"])
StaffDep = Annotated[CurrentUser, Depends(require_staff)]

# นานพอกันกล้องอ่านซ้ำ/staff เผลอสแกนสองที แต่ไม่นานจนบูธที่ต้องจ่ายซ้ำจริงติดขัด
GRANT_COOLDOWN_SECONDS = 20


@router.get("/attendees")
async def list_attendees(
    staff: StaffDep,
    q: str = "",
    event_day: int | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
):
    """ค้นรายชื่อ — ทางถอยตอน QR สแกนไม่ติด"""
    return await query_attendees(q, event_day, status, limit, cursor)


@router.post("/checkin/manual", response_model=CheckinOut)
async def manual_checkin(body: ManualCheckinIn, staff: StaffDep, request: Request):
    """เช็คชื่อจากรายชื่อ (ไม่ใช้ QR) — กรณีบัตรพัง/หาย/มือถือแบตหมด

    ★ ไม่มีคู่ยกเลิก — ยกเลิกเช็คอินเป็นสิทธิ์ของ admin เท่านั้น
      กดเช็คผิดคนเป็นเรื่องแก้ได้ (ให้ admin ถอน) แต่ถ้า staff ถอนเองได้
      ร่องรอยว่าใครเข้างานจริงจะเชื่อไม่ได้เลย
    """
    ticket = await Col.tickets().find_one({"user_id": ObjectId(body.user_id)})
    if not ticket:
        raise not_found("บัตร")
    if ticket["status"] == "revoked":
        return CheckinOut(result="revoked", event_day=body.event_day)

    out = await checkin_core(
        ticket=ticket,
        event_day=body.event_day,
        staff=staff,
        gate=body.gate,
        source="manual",
        device_id=None,
        scanned_at=None,
        idem_key=None,        # manual ไม่มี Idempotency-Key header → dedupe รายวันเป็นด่าน
        offline=False,
    )
    out.matched_by = "manual"
    await audit(request, staff, "checkin.manual", "user", body.user_id,
                {"event_day": body.event_day}, {"result": out.result})
    return out


@router.post(
    "/coins/grant",
    response_model=CoinGrantOut,
    dependencies=[Depends(require_writable), Depends(require_feature("quests", "การจ่ายเหรียญ"))],
)
async def grant_coins(
    body: CoinGrantIn,
    staff: StaffDep,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """staff จ่ายเหรียญให้คนเข้างาน — เลือกจำนวนแล้วสแกน

    ★ ไม่ผูกกับกิจกรรม บูธเก็บค่าเล่นเป็นเงินสดเอง ระบบจ่ายรางวัลอย่างเดียว

    ★ ตอบ 200 เสมอ ให้ staff อ่านที่ `result` — เหมือนหน้าเช็คอิน
      ถ้าโยน error ออกไป เครื่องสแกนจะขึ้นจอแดงเปล่าๆ ไม่บอกว่าต้องทำอะไรต่อ

    ★ กันจ่ายซ้ำ 2 ชั้น:
      1. Idempotency-Key จาก client — กดปุ่มรัวตอนเน็ตช้าได้ผลเดิม
      2. coins.award() ใช้ key เดียวกัน — ต่อให้ cache หลุด ledger ก็ไม่ซ้ำ

    ★ ทุกครั้งลง audit log — staff แจกเหรียญเป็นจุดที่โกงง่ายที่สุดในระบบทั้งหมด
      ต้องตามรอยได้ว่าใครจ่ายให้ใคร เท่าไหร่ เมื่อไหร่ จากเครื่องไหน
    """
    await ratelimit.check("checkin", body.device_id)

    if idempotency_key:
        if cached := await ratelimit.idempotent_get("grant", idempotency_key):
            return CoinGrantOut(**json.loads(cached))

    ticket, matched_by, reason, _code = await resolve_ticket(body.payload)
    if ticket is None:
        result = {
            "malformed": "invalid_sig", "invalid_sig": "invalid_sig",
            "wrong_version": "invalid_sig", "no_ticket": "no_ticket",
        }.get(reason, "not_found")
        return CoinGrantOut(
            result=result, matched_by=matched_by,
            message=REASON_MESSAGE.get(reason, "สแกนไม่สำเร็จ"),
        )

    if ticket["status"] == "revoked":
        return CoinGrantOut(
            result="revoked", matched_by=matched_by,
            message=REASON_MESSAGE["revoked"],
        )

    user_id = ticket["user_id"]
    user_doc = await Col.users().find_one(
        {"_id": user_id},
        {"display_name": 1, "full_name": 1, "avatar_url": 1, "student_id": 1},
    ) or {}
    user_public = {
        "display_name": user_doc.get("display_name", "?"),
        "full_name": user_doc.get("full_name"),
        "avatar_url": user_doc.get("avatar_url"),
        "student_id": user_doc.get("student_id"),
    }

    # ★ cooldown ต่อ (เครื่อง, บัตร) — ด่านที่กันความผิดพลาดจริงหน้างาน
    #   Idempotency-Key กันได้แค่ "ยิงซ้ำของ request เดียวกัน" (เน็ตช้าแล้วกดซ้ำ)
    #   แต่ถ้า staff ถือกล้องส่อง QR ค้างไว้ ทุกครั้งที่กล้องอ่านได้คือ "สแกนใหม่"
    #   มี key ใหม่ทุกครั้ง → จ่ายซ้ำได้ไม่จำกัด และไม่มีอะไรบอกว่าเกิดขึ้น
    #
    #   ตั้ง key ก่อนจ่าย (SET NX) — ถ้ามีคนชิงไปแล้วแปลว่าเพิ่งจ่ายไป
    #   ถ้าบูธต้องจ่ายซ้ำจริง รอให้ครบเวลาแล้วสแกนใหม่ได้
    cd_key = K.GRANT_COOLDOWN.format(device=body.device_id, ticket_id=str(ticket["_id"]))
    if not await get_redis().set(cd_key, str(body.amount), ex=GRANT_COOLDOWN_SECONDS, nx=True):
        return CoinGrantOut(
            result="duplicate", matched_by=matched_by, user=user_public,
            message=f"เพิ่งจ่ายให้คนนี้ไปเมื่อครู่ — ถ้าต้องจ่ายอีกจริง "
                    f"รอ {GRANT_COOLDOWN_SECONDS} วินาทีแล้วสแกนใหม่",
        )

    # ★ โควตารายวัน — จองก่อนจ่าย ไม่ใช่บันทึกหลังจ่าย
    #   ถ้านับหลังจ่าย ยอดที่เกินก็เข้ากระเป๋าไปแล้ว ต้องไปตามถอนทีหลัง
    limit = await grant_limits.reserve(staff.oid, user_id, body.amount)
    if not limit.ok:
        await get_redis().delete(cd_key)   # ไม่ได้จ่าย → ไม่ต้องติด cooldown
        return CoinGrantOut(
            result="limit_reached", matched_by=matched_by, user=user_public,
            message=limit.message, limit_kind=limit.limit_kind,
            limit_used=limit.used, limit_cap=limit.cap,
        )

    # ★ ไม่มี idempotency key (client เก่า/หลุด) → สร้างจากเวลา จะได้ไม่ชนกันเอง
    #   แต่ก็แปลว่ากดซ้ำจะจ่ายซ้ำ — frontend จึงส่ง key มาเสมอ
    idem = idempotency_key or f"auto:{ticket['ticket_code']}:{request.state.request_id}"
    res = await coins.award(
        user_id=user_id,
        amount=body.amount,
        reason="staff_grant",
        idempotency_key=f"grant:{idem}",
        ref={"type": "ticket", "id": str(ticket["_id"]), "device_id": body.device_id},
        actor_id=staff.oid,
        note=body.note or "จ่ายที่บูธ",
    )

    # ★ จ่ายไม่สำเร็จ (key ซ้ำ) → คืนโควตาที่จองไว้ ไม่งั้นโควตาหายฟรีทั้งที่ไม่ได้จ่าย
    if not res.awarded:
        await grant_limits.release(staff.oid, user_id, body.amount)

    quota = await grant_limits.usage(staff_id=staff.oid, user_id=user_id)
    out = CoinGrantOut(
        result="ok" if res.awarded else "duplicate",
        matched_by=matched_by,
        coins_awarded=body.amount if res.awarded else 0,
        new_balance=res.balance,
        user=user_public,
        message=(
            f"จ่าย {body.amount} เหรียญแล้ว — คงเหลือ {res.balance}"
            if res.awarded else "เพิ่งจ่ายไปแล้ว ไม่จ่ายซ้ำ"
        ),
        staff_used_today=quota.get("staff_used", 0),
        staff_cap_today=quota.get("staff_cap", 0),
    )

    if res.awarded:
        await audit(
            request, staff, "coins.grant", "user", str(user_id),
            {"balance": res.balance - body.amount},
            {"balance": res.balance, "amount": body.amount,
             "device_id": body.device_id, "note": body.note},
        )
        log.info("coins_granted", user_id=str(user_id), amount=body.amount,
                 staff_id=str(staff.oid), device=body.device_id)

    if idempotency_key:
        await ratelimit.idempotent_set("grant", idempotency_key, out.model_dump_json())
    return out
