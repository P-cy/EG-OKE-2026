"""โควตาการจ่ายเหรียญ — กันเหรียญเฟ้อและกัน staff จ่ายให้พวกพ้อง

staff_grant เป็นทางเดียวที่เหรียญเข้าระบบได้แบบไม่มีเพดานในตัว
เทสต์ชุดนี้ล็อกว่าแต่ละด่านปิดช่องโหว่ที่มันตั้งใจปิดจริง
"""
import pytest
from bson import ObjectId

from app.core.config import settings
from app.core.timeutil import th_date_key
from app.services import grant_limits


@pytest.fixture
def caps():
    """ตั้งเพดานเล็กๆ ให้เทสต์ชนได้เร็ว แล้วคืนค่าเดิม"""
    original = (
        settings.STAFF_GRANT_MAX_PER_SCAN,
        settings.STAFF_GRANT_PER_USER_DAILY,
        settings.USER_GRANT_RECEIVE_DAILY,
        settings.STAFF_GRANT_DAILY_BUDGET,
    )
    settings.STAFF_GRANT_MAX_PER_SCAN = 100
    settings.STAFF_GRANT_PER_USER_DAILY = 200
    settings.USER_GRANT_RECEIVE_DAILY = 500
    settings.STAFF_GRANT_DAILY_BUDGET = 1000
    yield
    (settings.STAFF_GRANT_MAX_PER_SCAN, settings.STAFF_GRANT_PER_USER_DAILY,
     settings.USER_GRANT_RECEIVE_DAILY, settings.STAFF_GRANT_DAILY_BUDGET) = original


# ── ด่านที่ 1: ต่อครั้ง ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_per_scan_ceiling(db, redis_clean, caps):
    """กันพิมพ์ผิดหลัก — ตั้งใจ 100 พิมพ์ 1000"""
    staff, user = ObjectId(), ObjectId()
    ok = await grant_limits.reserve(staff, user, 100)
    assert ok.ok

    too_much = await grant_limits.reserve(staff, ObjectId(), 101)
    assert not too_much.ok
    assert too_much.limit_kind == "per_scan"


# ── ด่านที่ 2: staff คนหนึ่ง → คนหนึ่ง ต่อวัน ────────────────────────────
@pytest.mark.asyncio
async def test_one_staff_cannot_keep_paying_one_friend(db, redis_clean, caps):
    """★ ด่านที่กัน "จ่ายให้เพื่อน" โดยตรง"""
    staff, friend = ObjectId(), ObjectId()

    assert (await grant_limits.reserve(staff, friend, 100)).ok
    assert (await grant_limits.reserve(staff, friend, 100)).ok   # ครบ 200 พอดี

    blocked = await grant_limits.reserve(staff, friend, 100)
    assert not blocked.ok
    assert blocked.limit_kind == "pair"
    assert blocked.used == 200 and blocked.cap == 200


@pytest.mark.asyncio
async def test_pair_limit_does_not_block_other_people(db, redis_clean, caps):
    """staff ที่ทำงานปกติต้องไม่ติดด่านนี้ — คนละคนคือคนละโควตา"""
    staff = ObjectId()
    friend = ObjectId()
    await grant_limits.reserve(staff, friend, 100)
    await grant_limits.reserve(staff, friend, 100)
    assert not (await grant_limits.reserve(staff, friend, 100)).ok

    stranger = await grant_limits.reserve(staff, ObjectId(), 100)
    assert stranger.ok, "คนอื่นต้องยังรับได้ตามปกติ"


# ── ด่านที่ 3: คนหนึ่งรับรวมทุกบูธ ต่อวัน ─────────────────────────────────
@pytest.mark.asyncio
async def test_one_person_cannot_farm_from_many_staff(db, redis_clean, caps):
    """★ ด่านที่กัน "ไล่เก็บจาก staff หลายคน"

    ด่าน pair กันได้ทีละคน แต่ถ้ามี staff รู้จัก 20 คน
    20 × 200 = 4,000 เหรียญต่อวัน ซึ่งพังอันดับทั้งงาน ด่านนี้ปิดท้าย
    """
    victim = ObjectId()
    total = 0
    for _ in range(10):                       # staff คนละคนทุกครั้ง
        res = await grant_limits.reserve(ObjectId(), victim, 100)
        if not res.ok:
            assert res.limit_kind == "receive"
            break
        total += 100
    else:
        pytest.fail("ต้องชนเพดานรับต่อวันก่อนครบ 10 รอบ")

    assert total == settings.USER_GRANT_RECEIVE_DAILY


# ── ด่านที่ 4: staff คนหนึ่งจ่ายรวม ต่อวัน ────────────────────────────────
@pytest.mark.asyncio
async def test_staff_daily_budget_is_the_circuit_breaker(db, redis_clean, caps):
    """เครื่องหลุดมือ → จ่ายให้คนละคนไปเรื่อยๆ ต้องมีเบรกเกอร์"""
    staff = ObjectId()
    paid = 0
    for _ in range(20):
        res = await grant_limits.reserve(staff, ObjectId(), 100)
        if not res.ok:
            assert res.limit_kind == "staff_daily"
            break
        paid += 100
    else:
        pytest.fail("ต้องชนเบรกเกอร์ก่อนครบ 20 รอบ")

    assert paid == settings.STAFF_GRANT_DAILY_BUDGET


# ── การจอง/คืน ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_blocked_reserve_does_not_consume_quota(db, redis_clean, caps):
    """★ ครั้งที่ถูกปฏิเสธต้องไม่กินโควตา

    ถ้ากิน = สแกนชนเพดานสิบครั้งแล้วโควตาหายจริงสิบเท่า
    ทั้งที่ไม่ได้จ่ายสักบาท
    """
    staff, friend = ObjectId(), ObjectId()
    await grant_limits.reserve(staff, friend, 100)
    await grant_limits.reserve(staff, friend, 100)

    for _ in range(5):
        assert not (await grant_limits.reserve(staff, friend, 100)).ok

    # ด่าน "รับต่อวัน" กับ "staff ต่อวัน" ต้องยังนับแค่ 200 ไม่ใช่ 700
    used = await grant_limits.usage(staff_id=staff, user_id=friend)
    assert used["staff_used"] == 200
    assert used["user_received"] == 200


@pytest.mark.asyncio
async def test_release_gives_the_quota_back(db, redis_clean, caps):
    """จ่ายไม่สำเร็จ (key ซ้ำ) → ต้องคืนโควตา ไม่งั้นหายฟรี"""
    staff, user = ObjectId(), ObjectId()
    await grant_limits.reserve(staff, user, 100)
    assert (await grant_limits.usage(staff_id=staff))["staff_used"] == 100

    await grant_limits.release(staff, user, 100)
    assert (await grant_limits.usage(staff_id=staff))["staff_used"] == 0


@pytest.mark.asyncio
async def test_admin_reset_clears_only_the_staff_budget(db, redis_clean, caps):
    """★ ล้างเบรกเกอร์ได้ แต่ห้ามล้างด่านกันพวกพ้อง

    ถ้าล้างได้หมด admin (หรือคนที่ยืม account admin) ก็ปลดล็อกได้ทุกอย่าง
    """
    staff, friend = ObjectId(), ObjectId()
    await grant_limits.reserve(staff, friend, 100)
    await grant_limits.reserve(staff, friend, 100)

    cleared = await grant_limits.reset_staff_budget(staff)
    assert cleared == 200

    usage = await grant_limits.usage(staff_id=staff, user_id=friend)
    assert usage["staff_used"] == 0, "โควตารวมของ staff ต้องถูกล้าง"
    assert usage["user_received"] == 200, "โควตาฝั่งผู้รับต้องไม่ถูกล้าง"

    still_blocked = await grant_limits.reserve(staff, friend, 100)
    assert not still_blocked.ok and still_blocked.limit_kind == "pair", \
        "ด่านกันจ่ายให้คนเดิมต้องยังทำงานหลังล้างเบรกเกอร์"


# ── ขอบวัน ─────────────────────────────────────────────────────────────
def test_day_key_follows_thai_calendar():
    """★ ต้องตัดวันตามเวลาไทย ไม่ใช่ UTC

    งานเลิก 5 ทุ่ม = 16:00 UTC ยังเป็นวันเดิม แต่ถ้าตัดด้วย UTC
    โควตาจะรีเซ็ตตอน 7 โมงเช้าซึ่งอยู่กลางงานพอดี
    """
    from datetime import datetime, timezone
    late_night_th = datetime(2026, 11, 13, 16, 30, tzinfo=timezone.utc)   # 23:30 ไทย
    next_morning_th = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)  # 01:00 ไทย วันถัดไป

    assert th_date_key(late_night_th) == "20261113"
    assert th_date_key(next_morning_th) == "20261114"
