"""ทดสอบระบบเควส (บูธกิจกรรม) — จ่ายเหรียญซ้ำไม่ได้

จุดที่พลาดแล้วเจ็บ: staff สแกนรัวสองครั้งที่บูธเดียวกัน ถ้ากันซ้ำด้วยการนับ
ก่อน insert (TOCTOU) จะจ่ายสองเด้ง เทสต์นี้ยิงพร้อมกันเพื่อพิสูจน์ว่า
unique index (quest_key, user_id, seq) กันได้จริง
"""
import asyncio

import pytest
from bson import ObjectId

from app.models.schemas import QuestClaimIn, QuestIn


# ── validation ─────────────────────────────────────────────────────────
def test_quest_key_must_be_slug():
    QuestIn(quest_key="booth-photo", title="บูธถ่ายรูป", coins=20)
    for bad in ("Booth Photo", "booth_photo", "บูธ", "A" * 40):
        with pytest.raises(Exception):
            QuestIn(quest_key=bad, title="x", coins=10)


def test_claim_accepts_all_three_code_forms():
    """เหมือน /checkin — QR เต็ม / รหัสบัตร / รหัสนักศึกษา ต้องผ่าน validation หมด"""
    for code in ("EGOKE2:1:EGOKE26-1E4A5AEE:1786070078:abc", "EGOKE26-1E4A5AEE", "6913099"):
        body = QuestClaimIn(quest_key="booth-photo", payload=code)
        assert body.payload == code


def test_coins_cannot_be_negative():
    with pytest.raises(Exception):
        QuestIn(quest_key="bad", title="x", coins=-10)


# ── integration ────────────────────────────────────────────────────────
@pytest.fixture
async def quest_fixture(db):
    await db["quests"].delete_many({})
    await db["quest_claims"].delete_many({})
    await db["quest_claims"].create_index(
        [("quest_key", 1), ("user_id", 1), ("seq", 1)], unique=True, name="uq_quest_user_seq"
    )
    await db["quests"].insert_one({
        "quest_key": "booth-photo", "title": "บูธถ่ายรูป", "description": "",
        "coins": 20, "status": "open", "max_per_user": 1, "sort_order": 1,
    })
    return "booth-photo"


@pytest.mark.asyncio
async def test_claim_awards_once_under_concurrent_scans(db, ticket_fixture, staff_user, quest_fixture):
    """★ สแกนรัว 8 ครั้งพร้อมกัน → จ่ายเหรียญครั้งเดียว"""
    from app.routers.quests import claim_quest

    body = QuestClaimIn(quest_key=quest_fixture, payload=ticket_fixture["ticket_code"])
    results = await asyncio.gather(*[claim_quest(body, staff_user) for _ in range(8)])

    oks = [r for r in results if r.result == "ok"]
    assert len(oks) == 1, f"ต้องผ่านครั้งเดียว ได้ {len(oks)}"
    assert oks[0].coins_awarded == 20

    user = await db["users"].find_one({"_id": ticket_fixture["user_id"]})
    assert user["coins_balance"] == 20, "จ่ายซ้ำ = เหรียญเฟ้อทั้งงาน"
    assert await db["quest_claims"].count_documents({"quest_key": quest_fixture}) == 1


@pytest.mark.asyncio
async def test_claim_respects_max_per_user(db, ticket_fixture, staff_user, quest_fixture):
    """max_per_user = 3 → รับได้ 3 ครั้งพอดี ครั้งที่ 4 เป็น duplicate"""
    from app.routers.quests import claim_quest

    await db["quests"].update_one({"quest_key": quest_fixture}, {"$set": {"max_per_user": 3}})
    body = QuestClaimIn(quest_key=quest_fixture, payload=ticket_fixture["ticket_code"])

    results = [await claim_quest(body, staff_user) for _ in range(5)]
    assert [r.result for r in results] == ["ok", "ok", "ok", "duplicate", "duplicate"]

    user = await db["users"].find_one({"_id": ticket_fixture["user_id"]})
    assert user["coins_balance"] == 60


@pytest.mark.asyncio
async def test_closed_quest_pays_nothing(db, ticket_fixture, staff_user, quest_fixture):
    from app.routers.quests import claim_quest

    await db["quests"].update_one({"quest_key": quest_fixture}, {"$set": {"status": "closed"}})
    res = await claim_quest(
        QuestClaimIn(quest_key=quest_fixture, payload=ticket_fixture["ticket_code"]), staff_user
    )
    assert res.result == "quest_closed" and res.coins_awarded == 0
    user = await db["users"].find_one({"_id": ticket_fixture["user_id"]})
    assert user["coins_balance"] == 0


@pytest.mark.asyncio
async def test_unknown_quest_reports_not_found(db, ticket_fixture, staff_user, quest_fixture):
    from app.routers.quests import claim_quest

    res = await claim_quest(
        QuestClaimIn(quest_key="ไม่มีจริง".encode().hex()[:20] or "nope",
                     payload=ticket_fixture["ticket_code"]),
        staff_user,
    )
    assert res.result == "not_found" and res.coins_awarded == 0


@pytest.mark.asyncio
async def test_claim_by_student_id_works(db, ticket_fixture, staff_user, quest_fixture):
    """มือถือแบตหมด → staff พิมพ์รหัสนักศึกษาแทนได้"""
    from app.routers.quests import claim_quest

    res = await claim_quest(QuestClaimIn(quest_key=quest_fixture, payload="6913099"), staff_user)
    assert res.result == "ok" and res.matched_by == "student_id" and res.coins_awarded == 20


@pytest.mark.asyncio
async def test_claim_with_garbage_code_is_rejected(db, ticket_fixture, staff_user, quest_fixture):
    from app.routers.quests import claim_quest

    res = await claim_quest(
        QuestClaimIn(quest_key=quest_fixture, payload="ขยะมั่วซั่ว"), staff_user
    )
    assert res.result == "invalid_sig" and res.coins_awarded == 0
    assert await db["quest_claims"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_claim_for_user_without_ticket(db, staff_user, quest_fixture):
    """คนที่ยังไม่ทำ onboarding → ไม่มีบัตร ต้องบอกให้ชัดว่าต่างจาก 'ไม่พบ'"""
    from app.routers.quests import claim_quest

    uid = ObjectId()
    await db["users"].insert_one({
        "_id": uid, "email": "noticket@student.mahidol.ac.th",
        "student_id": "6999999", "coins_balance": 0,
    })
    res = await claim_quest(QuestClaimIn(quest_key=quest_fixture, payload="6999999"), staff_user)
    assert res.result == "no_ticket" and res.coins_awarded == 0
