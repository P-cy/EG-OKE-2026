"""คิวจอ IG wall — ขึ้นจอคนละหนึ่งรอบ ไม่วนซ้ำ

★ ทำไมกติกาเป็นแบบนี้
  คนจ่าย 20 เหรียญเพื่อ "ได้ขึ้นจอ" หนึ่งรอบ ไม่ใช่เพื่อยึดจอทั้งงาน
  ของเดิมวนโชว์ใบเดิมไม่จบ ผลคือยิ่งงานดำเนินไป คิวยิ่งยาว คนที่เพิ่งจ่าย
  ต้องรอนานขึ้นเรื่อยๆ ตามจำนวนใบเก่าที่สะสมไว้

★ ทำไมให้ "จอ" เป็นคนแจ้งว่าฉายจบ ไม่ให้ backend จับเวลาเอง
  ถ้า backend นับเอง คิวจะไหลทิ้งแม้ไม่มีใครเปิดจอ — คนจ่ายตอนดึกแล้ว
  สิทธิ์หมดไปโดยไม่มีใครได้เห็น
  ทางนี้ถ้าจอดับ ใบนั้นค้างคิวไว้ รอบหน้าเปิดจอมาก็ได้ฉายต่อ (พังไปทางที่ปลอดภัยกว่า)
"""
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from app.core.config import settings
from app.routers.live import ig_wall, mark_ig_wall_shown
from app.core.errors import AppError


class _FakeRequest:
    client = type("C", (), {"host": "127.0.0.1"})()
    headers: dict = {}


class _FakeResponse:
    def __init__(self):
        self.headers: dict = {}


@pytest.fixture
async def wall_posts(db, redis_clean):
    """3 ใบที่อนุมัติแล้ว เรียงเวลา เก่า -> ใหม่"""
    uid = ObjectId()
    await db["users"].insert_one({
        "_id": uid, "email": "wall@example.com", "display_name": "คนส่ง",
        "roles": ["participant"], "status": "active", "coins_balance": 0,
    })
    base = datetime.now(timezone.utc)
    ids = []
    for i, name in enumerate(["ก", "ข", "ค"]):
        oid = ObjectId()
        ids.append(oid)
        await db["ig_submissions"].insert_one({
            "_id": oid, "user_id": uid, "status": "approved",
            "instagram_handle": f"post_{name}", "shortcode": f"wall{i}",
            "caption": f"ทดสอบ {name}", "image_data": "x" * 200,
            "submitted_at": base + timedelta(seconds=i),
            "reviewed_at": base + timedelta(seconds=i),
        })
    yield ids
    await db["ig_submissions"].delete_many({"_id": {"$in": ids}})
    await db["users"].delete_one({"_id": uid})


async def _queue() -> list[str]:
    out = await ig_wall(_FakeRequest(), _FakeResponse(), limit=30)
    return [i["instagram_handle"] for i in out["items"]]


async def _ids() -> list[str]:
    out = await ig_wall(_FakeRequest(), _FakeResponse(), limit=30)
    return [i["id"] for i in out["items"]]


# ── ลำดับคิว ─────────────────────────────────────────────────────────────

async def test_queue_starts_oldest_first(wall_posts):
    """เก่าสุดอยู่หัวคิว — คนที่รอมานานที่สุดได้ขึ้นก่อน"""
    assert await _queue() == ["post_ก", "post_ข", "post_ค"]


async def test_shown_post_leaves_the_queue_for_good(wall_posts):
    """★ ข้อหลักของไฟล์นี้: ฉายจบแล้วต้องไม่กลับมาอีก"""
    first = (await _ids())[0]
    await mark_ig_wall_shown(first, token=settings.DISPLAY_TOKEN)
    assert await _queue() == ["post_ข", "post_ค"]

    # เรียกซ้ำอีกกี่รอบก็ต้องไม่โผล่กลับมา
    for _ in range(3):
        assert "post_ก" not in await _queue()


async def test_queue_drains_completely(wall_posts):
    """ฉายครบทุกใบแล้วคิวต้องว่าง ไม่ใช่วนกลับไปใบแรก"""
    for _ in range(3):
        ids = await _ids()
        await mark_ig_wall_shown(ids[0], token=settings.DISPLAY_TOKEN)
    assert await _queue() == []


async def test_new_post_joins_the_back_of_the_queue(db, wall_posts):
    """ใบใหม่ต่อท้าย ไม่แทรกคิว — ใบที่กำลังฉายอยู่ต้องได้เวลาเต็ม"""
    await mark_ig_wall_shown((await _ids())[0], token=settings.DISPLAY_TOKEN)

    newer = ObjectId()
    await db["ig_submissions"].insert_one({
        "_id": newer, "user_id": ObjectId(), "status": "approved",
        "instagram_handle": "post_ใหม่", "shortcode": "wall_new",
        "image_data": "x" * 200,
        "submitted_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        "reviewed_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    })
    try:
        assert await _queue() == ["post_ข", "post_ค", "post_ใหม่"]
    finally:
        await db["ig_submissions"].delete_one({"_id": newer})


# ── สิทธิ์ ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_token", ["", "wrong", "DISPLAY_TOKEN"])
async def test_marking_shown_requires_the_display_token(wall_posts, bad_token):
    """★ endpoint นี้ "เผา" สิทธิ์ที่คนจ่ายเหรียญซื้อมา

    ถ้าเปิดโล่ง ใครก็ยิงรัวให้โพสต์คนอื่นหายจากคิวได้หมด
    งานนี้มีผู้เข้าร่วมหลายพันคนและ URL เป็น public — จะมีคนลองแน่นอน
    """
    first = (await _ids())[0]
    with pytest.raises(AppError) as e:
        await mark_ig_wall_shown(first, token=bad_token)
    assert e.value.status_code == 401
    # ของยังอยู่ในคิวครบ
    assert await _queue() == ["post_ก", "post_ข", "post_ค"]


# ── ยิงซ้ำ ───────────────────────────────────────────────────────────────

async def test_marking_twice_does_not_rewrite_the_timestamp(db, wall_posts):
    """จอ reconnect แล้วส่งซ้ำได้ ไม่ควรทำให้เวลาที่บันทึกไว้เพี้ยน"""
    first = (await _ids())[0]
    r1 = await mark_ig_wall_shown(first, token=settings.DISPLAY_TOKEN)
    doc = await db["ig_submissions"].find_one({"_id": ObjectId(first)})
    stamped = doc["wall_shown_at"]

    r2 = await mark_ig_wall_shown(first, token=settings.DISPLAY_TOKEN)
    doc2 = await db["ig_submissions"].find_one({"_id": ObjectId(first)})

    assert r1["marked"] is True and r2["marked"] is False
    assert doc2["wall_shown_at"] == stamped


async def test_unknown_id_is_not_found(wall_posts):
    with pytest.raises(AppError) as e:
        await mark_ig_wall_shown("ไม่ใช่ ObjectId", token=settings.DISPLAY_TOKEN)
    assert e.value.status_code == 404
