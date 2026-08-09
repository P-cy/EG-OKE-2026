"""Quests — บูธกิจกรรมหน้างาน

flow: คนเข้างานเดินไปบูธ → เปิดหน้าบัตร QR → staff เลือกกิจกรรม + สแกน → ได้เหรียญ

ใช้ทางเข้าเดียวกับเช็คอิน (resolve_ticket) → สแกน QR / พิมพ์รหัสบัตร / รหัสนักศึกษา
ก็ได้เหมือนกัน ไม่ต้องสอน staff ใหม่

★ กันรับซ้ำด้วย unique index (quest_key, user_id, seq) ไม่ใช่แค่ count
  ถ้าใช้ count แล้วเช็คก่อน insert จะเป็น TOCTOU — สแกนรัวสองครั้งได้เหรียญสองเด้ง
"""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pymongo.errors import DuplicateKeyError

from app.core import ratelimit
from app.core.db import Col
from app.core.deps import CurrentUser, CurrentUserDep, require_feature, require_staff
from app.core.observability import log
from app.models.schemas import QuestClaimIn, QuestClaimOut, QuestPublic
from app.routers.checkin import REASON_MESSAGE, resolve_ticket
from app.services import coins

router = APIRouter(prefix="/quests", tags=["quests"])


@router.get("", response_model=list[QuestPublic])
async def list_quests(user: CurrentUserDep):
    """กิจกรรมที่เปิดอยู่ + ผู้ใช้คนนี้รับไปแล้วกี่ครั้ง"""
    rows = await Col.quests().find({"status": "open"}).sort("sort_order", 1).to_list(100)
    keys = [q["quest_key"] for q in rows]

    # นับของตัวเองทีเดียวด้วย aggregate — ไม่ยิงทีละ quest
    mine: dict[str, int] = {}
    if keys:
        cursor = Col.quest_claims().aggregate([
            {"$match": {"user_id": user.oid, "quest_key": {"$in": keys}}},
            {"$group": {"_id": "$quest_key", "n": {"$sum": 1}}},
        ])
        mine = {r["_id"]: r["n"] async for r in cursor}

    return [
        QuestPublic(
            quest_key=q["quest_key"], title=q["title"],
            description=q.get("description", ""), coins=q.get("coins", 0),
            status=q["status"], max_per_user=q.get("max_per_user", 1),
            sort_order=q.get("sort_order", 0),
            my_claims=mine.get(q["quest_key"], 0),
        )
        for q in rows
    ]


@router.post(
    "/claim",
    response_model=QuestClaimOut,
    dependencies=[Depends(require_feature("quests", "กิจกรรม"))],
)
async def claim_quest(
    body: QuestClaimIn,
    staff: Annotated[CurrentUser, Depends(require_staff)],
):
    """staff สแกนที่บูธ → จ่ายเหรียญให้คนเข้างาน

    ตอบ 200 เสมอ ให้ staff อ่านที่ `result` เหมือนหน้าเช็คอิน
    """
    await ratelimit.check("checkin", body.device_id)
    now = datetime.now(timezone.utc)

    quest = await Col.quests().find_one({"quest_key": body.quest_key})
    if not quest:
        return QuestClaimOut(result="not_found", message="ไม่พบกิจกรรมนี้ — ตรวจว่าเลือกถูกไหม")
    if quest.get("status") != "open":
        return QuestClaimOut(
            result="quest_closed", quest_key=body.quest_key, quest_title=quest.get("title"),
            message="กิจกรรมนี้ปิดแล้ว — ให้ admin เปิดก่อนจึงจะแจกเหรียญได้",
        )

    ticket, matched_by, reason, _code = await resolve_ticket(body.payload)
    if ticket is None:
        result = {
            "malformed": "invalid_sig", "invalid_sig": "invalid_sig",
            "wrong_version": "invalid_sig", "no_ticket": "no_ticket",
        }.get(reason, "not_found")
        return QuestClaimOut(
            result=result, matched_by=matched_by,
            quest_key=body.quest_key, quest_title=quest.get("title"),
            message=REASON_MESSAGE.get(reason, "สแกนไม่สำเร็จ"),
        )

    user_id = ticket["user_id"]
    user_doc = await Col.users().find_one(
        {"_id": user_id}, {"display_name": 1, "full_name": 1, "avatar_url": 1, "student_id": 1}
    ) or {}
    user_public = {
        "display_name": user_doc.get("display_name", "?"),
        "full_name": user_doc.get("full_name"),
        "avatar_url": user_doc.get("avatar_url"),
        "student_id": user_doc.get("student_id"),
    }

    max_per_user = int(quest.get("max_per_user", 1))
    used = await Col.quest_claims().count_documents(
        {"quest_key": body.quest_key, "user_id": user_id}
    )

    # ★ จองสิทธิ์ด้วย unique index ก่อน แล้วค่อยจ่ายเหรียญ
    #   seq = ครั้งที่เท่าไหร่ → กดรัวพร้อมกันจะชน index ทันที ไม่ต้องพึ่งผลนับ
    seq = used + 1
    if seq > max_per_user:
        return QuestClaimOut(
            result="duplicate", matched_by=matched_by, user=user_public,
            quest_key=body.quest_key, quest_title=quest.get("title"),
            claims_used=used, max_per_user=max_per_user,
            message=f"รับกิจกรรมนี้ครบ {max_per_user} ครั้งแล้ว",
        )

    coins_amount = int(quest.get("coins", 0))
    try:
        await Col.quest_claims().insert_one({
            "quest_key": body.quest_key,
            "user_id": user_id,
            "seq": seq,
            "ticket_code": ticket["ticket_code"],
            "coins_awarded": coins_amount,
            "staff_id": staff.oid,
            "device_id": body.device_id,
            "source": matched_by,
            "claimed_at": now,
            "schema_version": 1,
        })
    except DuplicateKeyError:
        # มีคนสแกนพร้อมกัน/สแกนซ้ำ — ครั้งนี้ไม่นับ
        return QuestClaimOut(
            result="duplicate", matched_by=matched_by, user=user_public,
            quest_key=body.quest_key, quest_title=quest.get("title"),
            claims_used=used, max_per_user=max_per_user,
            message="เพิ่งรับไปแล้ว ไม่จ่ายซ้ำ",
        )

    awarded = 0
    if coins_amount > 0:
        res = await coins.award(
            user_id=user_id, amount=coins_amount, reason="quest",
            idempotency_key=f"quest:{body.quest_key}:{user_id}:{seq}",
            ref={"type": "quest", "id": body.quest_key},
            note=quest.get("title", ""),
        )
        awarded = coins_amount if res.awarded else 0

    log.info("quest_claimed", quest=body.quest_key, user_id=str(user_id),
             seq=seq, coins=awarded, staff_id=str(staff.oid))

    return QuestClaimOut(
        result="ok", matched_by=matched_by, user=user_public,
        quest_key=body.quest_key, quest_title=quest.get("title"),
        coins_awarded=awarded, claims_used=seq, max_per_user=max_per_user,
        message=f"{quest.get('title', 'กิจกรรม')} +{awarded} coin",
    )
