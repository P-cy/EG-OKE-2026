"""เหรียญที่จ่ายไปแล้วแต่ไม่ได้ของ ต้องคืน

สองเส้นทางที่เคยกินเหรียญผู้ใช้ไปเงียบๆ:
  · ปฏิเสธรูป IG — จ่าย 20 เหรียญเพื่อ "ขึ้นจอ" แล้ว admin ไม่อนุมัติ เหรียญหายไปเฉยๆ
  · หมุนวงล้อแล้ว nonce ชน — หักเหรียญตั้งแต่ขั้นแรก แต่ insert ไม่ผ่านแล้ว raise ทิ้ง
"""
import asyncio
from datetime import datetime, timezone

import pytest
from bson import ObjectId

from app.models.schemas import SpinIn


class _FakeRequest:
    """Request ปลอมสำหรับ audit() — ต้องการแค่ client/headers"""
    client = type("C", (), {"host": "127.0.0.1"})()
    headers: dict = {}


@pytest.fixture
async def paying_user(db, redis_clean):
    uid = ObjectId()
    await db["users"].insert_one({
        "_id": uid, "email": "payer@test.local", "display_name": "คนจ่าย",
        "roles": ["participant"], "status": "active", "coins_balance": 100,
        "created_at": datetime.now(timezone.utc),
    })
    return uid


# ── IG: ปฏิเสธแล้วต้องคืนเหรียญ ────────────────────────────────────────
@pytest.mark.asyncio
async def test_reject_refunds_the_submission_fee(db, paying_user):
    from app.core.deps import CurrentUser
    from app.routers.admin import reject_ig
    from app.routers.ig import WALL_COST

    admin = CurrentUser(id=str(ObjectId()), roles=["admin"], jti="j")
    await db["ig_submissions"].delete_many({})
    res = await db["ig_submissions"].insert_one({
        "user_id": paying_user, "shortcode": "local:refund-me", "post_url": "",
        "instagram_handle": "someone", "caption": "", "image_data": "x" * 200,
        "status": "pending", "coins_awarded": 0,
        "submitted_at": datetime.now(timezone.utc),
    })
    # จำลองว่าจ่ายค่าส่งไปแล้ว
    await db["users"].update_one({"_id": paying_user}, {"$inc": {"coins_balance": -WALL_COST}})

    out = await reject_ig(str(res.inserted_id), admin, _FakeRequest())

    assert out["coins_refunded"] == WALL_COST
    user = await db["users"].find_one({"_id": paying_user})
    assert user["coins_balance"] == 100, "ต้องกลับไปเท่าก่อนส่ง"
    sub = await db["ig_submissions"].find_one({"_id": res.inserted_id})
    assert sub["status"] == "rejected"


@pytest.mark.asyncio
async def test_reject_twice_refunds_once(db, paying_user):
    """★ กดปฏิเสธรัวสองครั้ง (หรือสอง admin พร้อมกัน) ต้องไม่คืนเหรียญสองเด้ง"""
    from app.core.deps import CurrentUser
    from app.core.errors import AppError
    from app.routers.admin import reject_ig
    from app.routers.ig import WALL_COST

    admin = CurrentUser(id=str(ObjectId()), roles=["admin"], jti="j")
    await db["ig_submissions"].delete_many({})
    res = await db["ig_submissions"].insert_one({
        "user_id": paying_user, "shortcode": "local:refund-once", "post_url": "",
        "status": "pending", "coins_awarded": 0, "image_data": "x" * 200,
        "submitted_at": datetime.now(timezone.utc),
    })
    await db["users"].update_one({"_id": paying_user}, {"$inc": {"coins_balance": -WALL_COST}})

    await reject_ig(str(res.inserted_id), admin, _FakeRequest())
    with pytest.raises(AppError):
        await reject_ig(str(res.inserted_id), admin, _FakeRequest())

    user = await db["users"].find_one({"_id": paying_user})
    assert user["coins_balance"] == 100, "คืนซ้ำ = เหรียญเฟ้อ"


# ── Wheel: nonce ชนแล้วต้องคืนค่าหมุน ──────────────────────────────────
@pytest.fixture
async def open_wheel(db):
    await db["wheel_spins"].delete_many({})
    await db["wheel_spins"].create_index(
        [("user_id", 1), ("wheel_key", 1), ("nonce", 1)], unique=True, name="uq_user_nonce"
    )
    await db["wheel_spins"].create_index("idempotency_key", unique=True, name="uq_idem")
    await db["wheel_configs"].delete_many({})
    await db["wheel_configs"].insert_one({
        "wheel_key": "t-wheel", "title": "วงล้อทดสอบ", "cost_coins": 20,
        "status": "open", "max_spins_per_user": 3,
        "segments": [
            {"id": "s1", "label": "ไม่ถูกรางวัล", "weight": 1, "remaining": None, "prize_type": "none"},
        ],
        "server_seed": "seed-for-test", "commit_hash": "hash",
    })
    return "t-wheel"


@pytest.mark.asyncio
async def test_duplicate_nonce_refunds_the_spin_cost(db, paying_user, open_wheel):
    """★ nonce ซ้ำ = การหมุนไม่ถูกบันทึก แต่เหรียญถูกหักไปแล้วตั้งแต่ขั้นที่ 1

    ของเดิม raise ทิ้งเฉยๆ → ผู้ใช้เสีย 20 เหรียญโดยไม่ได้หมุน
    (frontend เก่าสุ่ม nonce 1..1000 จึงชนกันเองได้จริงหลายสิบคนในงาน 5,000 คน)
    """
    from app.core.deps import CurrentUser
    from app.core.errors import AppError
    from app.routers.wheel import spin

    user = CurrentUser(id=str(paying_user), roles=["participant"], jti="j")

    first = await spin(open_wheel, SpinIn(client_seed="abc", nonce=1), user, "idem-1")
    assert first.coins_spent == 20
    after_first = (await db["users"].find_one({"_id": paying_user}))["coins_balance"]
    assert after_first == 80

    # nonce เดิม แต่ Idempotency-Key ใหม่ → ไม่โดน cache ไปชน unique index เต็มๆ
    with pytest.raises(AppError) as err:
        await spin(open_wheel, SpinIn(client_seed="abc", nonce=1), user, "idem-2")
    assert err.value.code == "NONCE_ALREADY_USED"

    balance = (await db["users"].find_one({"_id": paying_user}))["coins_balance"]
    assert balance == 80, "เหรียญของครั้งที่ล้มเหลวต้องถูกคืน"
    assert await db["wheel_spins"].count_documents({"user_id": paying_user}) == 1


@pytest.mark.asyncio
async def test_concurrent_spins_never_exceed_quota(db, paying_user, open_wheel):
    """ยิงพร้อมกัน 8 ครั้งด้วย nonce ต่างกัน → หมุนได้ไม่เกินโควตา และเหรียญตรง"""
    from app.core.deps import CurrentUser
    from app.routers.wheel import spin

    user = CurrentUser(id=str(paying_user), roles=["participant"], jti="j")
    results = await asyncio.gather(*[
        spin(open_wheel, SpinIn(client_seed="s", nonce=i), user, f"idem-{i}")
        for i in range(1, 9)
    ], return_exceptions=True)

    ok = [r for r in results if not isinstance(r, Exception)]
    stored = await db["wheel_spins"].count_documents({"user_id": paying_user})
    assert len(ok) <= 3, f"หมุนเกินโควตา: สำเร็จ {len(ok)} ครั้ง (max 3)"
    assert stored == len(ok)

    balance = (await db["users"].find_one({"_id": paying_user}))["coins_balance"]
    assert balance == 100 - 20 * len(ok), "ยอดต้องตรงกับจำนวนที่หมุนสำเร็จจริง"
    assert balance >= 0
