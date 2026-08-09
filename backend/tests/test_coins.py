"""ทดสอบ ledger เหรียญ — เงินคนอื่นพลาดไม่ได้

จุดที่เคยพัง: ทางเรียก `balance_of()` แล้วค่อย `award(-cost)` เป็น TOCTOU
ยิงพร้อมกันผ่านด่านเช็คทั้งคู่ → ยอดติดลบ ตอนนี้ใช้ coins.spend() ที่ atomic
"""
import asyncio

import pytest
from bson import ObjectId

from app.services import coins


@pytest.mark.asyncio
async def test_award_is_idempotent(db):
    uid = ObjectId()
    await db["users"].insert_one({"_id": uid, "coins_balance": 0})

    for _ in range(5):
        await coins.award(uid, 10, "checkin", idempotency_key="same-key")

    user = await db["users"].find_one({"_id": uid})
    assert user["coins_balance"] == 10, "key เดิมต้องให้เหรียญครั้งเดียว"
    assert await db["coin_transactions"].count_documents({"user_id": uid}) == 1


@pytest.mark.asyncio
async def test_spend_never_goes_negative_under_concurrency(db):
    """★ เทสต์ที่สำคัญที่สุดในไฟล์นี้

    มี 50 เหรียญ ยิงจ่ายครั้งละ 20 พร้อมกัน 10 ครั้ง
    → ต้องสำเร็จแค่ 2 ครั้ง (40) เหลือ 10 ห้ามติดลบ
    """
    uid = ObjectId()
    await db["users"].insert_one({"_id": uid, "coins_balance": 50})

    results = await asyncio.gather(*[
        coins.spend(uid, 20, "wheel_cost", idempotency_key=f"spin-{i}")
        for i in range(10)
    ])

    ok = [r for r in results if r.awarded]
    assert len(ok) == 2, f"ต้องหักได้ 2 ครั้ง ได้ {len(ok)}"
    assert all(r.insufficient for r in results if not r.awarded)

    user = await db["users"].find_one({"_id": uid})
    assert user["coins_balance"] == 10
    assert user["coins_balance"] >= 0, "ยอดติดลบ = บั๊กร้ายแรง"


@pytest.mark.asyncio
async def test_spend_reports_insufficient_not_awarded(db):
    uid = ObjectId()
    await db["users"].insert_one({"_id": uid, "coins_balance": 5})

    res = await coins.spend(uid, 20, "wheel_cost", idempotency_key="k1")
    assert not res.awarded and res.insufficient and res.balance == 5
    assert await db["coin_transactions"].count_documents({"user_id": uid}) == 0, \
        "หักไม่สำเร็จต้องไม่มี ledger row"


@pytest.mark.asyncio
async def test_spend_same_key_twice_does_not_double_charge(db):
    """กดปุ่มสองครั้งด้วย idempotency key เดิม → หักครั้งเดียว"""
    uid = ObjectId()
    await db["users"].insert_one({"_id": uid, "coins_balance": 100})

    a = await coins.spend(uid, 20, "ig_wall", idempotency_key="dup")
    b = await coins.spend(uid, 20, "ig_wall", idempotency_key="dup")

    assert a.awarded and not b.awarded
    user = await db["users"].find_one({"_id": uid})
    assert user["coins_balance"] == 80, "หักซ้ำ = ผู้ใช้เสียเหรียญฟรี"


@pytest.mark.asyncio
async def test_ledger_is_source_of_truth(db):
    """balance เพี้ยน → reconcile ต้องดึงกลับมาให้ตรง ledger"""
    uid = ObjectId()
    await db["users"].insert_one({"_id": uid, "coins_balance": 0})
    await coins.award(uid, 30, "checkin", idempotency_key="a")

    # จำลอง balance เพี้ยน (โปรเซสตายกลางทาง / แก้มือ)
    await db["users"].update_one({"_id": uid}, {"$set": {"coins_balance": 999}})

    result = await coins.reconcile_all(fix=True)
    assert result["drift"] >= 1 and result["fixed"] >= 1

    user = await db["users"].find_one({"_id": uid})
    assert user["coins_balance"] == 30 == await coins.ledger_sum(uid)


@pytest.mark.asyncio
async def test_spend_rejects_non_positive_amount(db):
    with pytest.raises(ValueError):
        await coins.spend(ObjectId(), -5, "bad", idempotency_key="x")
    with pytest.raises(ValueError):
        await coins.spend(ObjectId(), 0, "bad", idempotency_key="y")
