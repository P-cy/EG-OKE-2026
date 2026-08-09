"""Rate limit ต้องรอดจาก NAT ของงาน

บริบท: ผู้เข้าร่วม 5,000 คนอยู่บน WiFi มหาลัยเดียวกัน → ออกเน็ตด้วย IP เดียว
ถ้า endpoint ที่ทุกคนเรียกถูกจำกัด "ต่อ IP" ทุกคนจะโดน 429 พร้อมกัน
ซึ่งคือสิ่งที่ load test เจอจริง: /live/snapshot เพดาน 120/นาที ต่อ IP
แต่ของจริงคือ 5,000 เครื่อง × 20 ครั้ง/นาที = 100,000 ครั้ง/นาที จาก IP เดียว
"""
import pytest

from app.core import ratelimit


class _Req:
    """Request ปลอม — ratelimit ใช้แค่ headers กับ client.host"""

    def __init__(self, ip: str = "10.0.0.1", token: str | None = None):
        self.headers = {"authorization": f"Bearer {token}"} if token else {}
        self.client = type("C", (), {"host": ip})()


def _token(user_id: str) -> str:
    from app.core.security import create_access_token
    return create_access_token(user_id, ["participant"])[0]


@pytest.mark.asyncio
async def test_live_limit_is_per_user_not_per_ip(redis_clean):
    """★ 200 เครื่องหลัง IP เดียวกัน ต้องผ่านหมด

    เพดาน live = 120/นาที ถ้ายังนับต่อ IP อยู่ เครื่องที่ 121 เป็นต้นไปจะโดน 429
    """

    shared_ip = "203.0.113.9"          # IP เดียวกันทั้งหมด — จำลอง NAT ของงาน
    for i in range(200):
        req = _Req(ip=shared_ip, token=_token(f"6a7000000000000000000{i:03d}"))
        await ratelimit.check_public("live", req)   # ต้องไม่ raise


@pytest.mark.asyncio
async def test_same_user_polling_too_fast_still_limited(redis_clean):
    """แต่ละเครื่องยังต้องมีเพดานของตัวเอง — ไม่ใช่เปิดฟรี"""
    from app.core.errors import AppError

    uid = "6a7000000000000000000fff"
    req = _Req(ip="203.0.113.9", token=_token(uid))
    limit = ratelimit.LIMITS["live"].requests

    for _ in range(limit):
        await ratelimit.check_public("live", req)

    with pytest.raises(AppError) as e:
        await ratelimit.check_public("live", req)
    assert e.value.status_code == 429 and e.value.code == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_anonymous_falls_back_to_ip_with_room_to_spare(redis_clean):
    """คนที่ยังไม่ login แชร์ bucket ตาม IP — เพดานต้องสูงพอสำหรับจอใหญ่ + คนตกหล่น"""
    anon = ratelimit.LIMITS["live_anon"]
    assert anon.requests >= 1000, "เพดาน anon ต่ำเกินไปสำหรับ IP เดียวทั้งงาน"

    req = _Req(ip="203.0.113.10")
    for _ in range(300):
        await ratelimit.check_public("live", req)   # ต้องไม่ raise


@pytest.mark.asyncio
async def test_invalid_token_falls_back_to_ip_bucket(redis_clean):
    """ส่ง token มั่ว/หมดอายุมา ต้องไม่ crash — ถือว่าเป็น anonymous"""
    req = _Req(ip="203.0.113.11", token="ไม่ใช่-jwt-จริง")
    await ratelimit.check_public("live", req)


def test_every_high_traffic_scope_is_documented():
    """กันคนเพิ่ม scope ใหม่แล้วลืมคิดเรื่อง NAT"""
    assert "live_anon" in ratelimit.LIMITS, "scope สาธารณะต้องมีคู่ _anon ของตัวเอง"
    assert ratelimit.LIMITS["live_anon"].requests > ratelimit.LIMITS["live"].requests
