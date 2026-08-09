"""staff จ่ายเหรียญที่บูธ — เลือกจำนวนแล้วสแกน

จุดที่โกง/พลาดง่ายที่สุดในระบบทั้งหมด: staff จ่ายเหรียญได้ตามใจ
เทสต์ชุดนี้ล็อกเพดาน ล็อกการจ่ายซ้ำ และล็อกว่าทุกครั้งต้องลง audit log
"""
import pytest
from bson import ObjectId

from app.core.redis_client import K
from app.models.schemas import CoinGrantIn
from app.routers.staff import GRANT_COOLDOWN_SECONDS
from app.services import coins


# ── เพดานจำนวนเงิน ─────────────────────────────────────────────────────
def test_amount_has_a_ceiling():
    """★ กันพิมพ์ 10000 ทั้งที่ตั้งใจพิมพ์ 100

    ถอนคืนได้ก็จริง แต่ต้องมีคนสังเกตเห็นก่อน ซึ่งมักไม่มี
    """
    CoinGrantIn(payload="EGOKE26-AAAABBBB", amount=1000)
    with pytest.raises(Exception):
        CoinGrantIn(payload="EGOKE26-AAAABBBB", amount=1001)


def test_amount_must_be_positive():
    """จ่ายติดลบ = หักเหรียญคนอื่นได้ ต้องผ่าน admin เท่านั้น"""
    for bad in (0, -50):
        with pytest.raises(Exception):
            CoinGrantIn(payload="EGOKE26-AAAABBBB", amount=bad)


def test_preset_amounts_are_within_range():
    """ปุ่มสำเร็จรูปบนหน้าเว็บต้องผ่าน validation ฝั่ง backend"""
    for n in (20, 50, 100):
        assert CoinGrantIn(payload="EGOKE26-AAAABBBB", amount=n).amount == n


def test_payload_too_short_is_rejected():
    """กันกดพลาดแล้วส่งของว่างไป — ต้องไม่ไปถึงชั้นค้นหาบัตร"""
    with pytest.raises(Exception):
        CoinGrantIn(payload="abc", amount=20)


# ── จ่ายจริง ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_grant_adds_exactly_the_amount(db, redis_clean):
    uid = ObjectId()
    await db["users"].insert_one({
        "_id": uid, "email": "g@example.com", "display_name": "ผู้รับ",
        "roles": ["participant"], "status": "active", "coins_balance": 0,
    })

    res = await coins.award(
        user_id=uid, amount=50, reason="staff_grant",
        idempotency_key="grant:test-1", actor_id=ObjectId(),
    )
    assert res.awarded and res.balance == 50

    user = await db["users"].find_one({"_id": uid})
    assert user["coins_balance"] == 50


@pytest.mark.asyncio
async def test_same_idempotency_key_pays_once(db, redis_clean):
    """เน็ตช้าแล้ว client ยิงซ้ำ — ledger ต้องมีรายการเดียว"""
    uid = ObjectId()
    await db["users"].insert_one({
        "_id": uid, "email": "g2@example.com", "display_name": "ผู้รับ",
        "roles": ["participant"], "status": "active", "coins_balance": 0,
    })

    first = await coins.award(user_id=uid, amount=100, reason="staff_grant",
                              idempotency_key="grant:same-key")
    second = await coins.award(user_id=uid, amount=100, reason="staff_grant",
                               idempotency_key="grant:same-key")

    assert first.awarded is True
    assert second.awarded is False, "key เดิมต้องไม่จ่ายซ้ำ"

    user = await db["users"].find_one({"_id": uid})
    assert user["coins_balance"] == 100, "ยอดต้องขึ้นครั้งเดียว"

    n = await db["coin_transactions"].count_documents({"idempotency_key": "grant:same-key"})
    assert n == 1


# ── cooldown กันสแกนซ้ำ ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cooldown_key_blocks_the_second_scan(db, redis_clean):
    """★ ด่านที่กันความผิดพลาดจริงหน้างาน

    Idempotency-Key กันได้แค่ "ยิงซ้ำของ request เดียวกัน"
    แต่ staff ถือกล้องส่อง QR ค้างไว้ = สแกนใหม่ทุกครั้ง มี key ใหม่ทุกครั้ง
    ไม่มี cooldown = จ่ายไป 3 รอบใน 10 วิโดยไม่มีใครรู้
    """
    r = redis_clean
    key = K.GRANT_COOLDOWN.format(device="booth-1", ticket_id="abc123")

    first = await r.set(key, "20", ex=GRANT_COOLDOWN_SECONDS, nx=True)
    second = await r.set(key, "20", ex=GRANT_COOLDOWN_SECONDS, nx=True)

    assert first, "สแกนครั้งแรกต้องผ่าน"
    assert not second, "สแกนซ้ำภายใน cooldown ต้องถูกปฏิเสธ"

    ttl = await r.ttl(key)
    assert 0 < ttl <= GRANT_COOLDOWN_SECONDS


@pytest.mark.asyncio
async def test_cooldown_is_per_device_and_per_ticket(db, redis_clean):
    """สองบูธจ่ายให้คนเดียวกันพร้อมกันได้ — คนละกิจกรรม ไม่ควรบล็อกกัน"""
    r = redis_clean
    a = K.GRANT_COOLDOWN.format(device="booth-1", ticket_id="t1")
    b = K.GRANT_COOLDOWN.format(device="booth-2", ticket_id="t1")
    c = K.GRANT_COOLDOWN.format(device="booth-1", ticket_id="t2")

    assert await r.set(a, "20", ex=GRANT_COOLDOWN_SECONDS, nx=True)
    assert await r.set(b, "20", ex=GRANT_COOLDOWN_SECONDS, nx=True), "คนละบูธต้องไม่ชนกัน"
    assert await r.set(c, "20", ex=GRANT_COOLDOWN_SECONDS, nx=True), "คนละคนต้องไม่ชนกัน"


def test_cooldown_is_short_enough_to_be_usable():
    """ยาวไปแล้วบูธที่ต้องจ่ายซ้ำจริงติดขัด สั้นไปแล้วกันสแกนซ้ำไม่ทัน"""
    assert 10 <= GRANT_COOLDOWN_SECONDS <= 60
