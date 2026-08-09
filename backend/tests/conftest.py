"""fixture สำหรับ integration test — ใช้ Mongo/Redis จริงจาก docker compose

หลักการ: ไม่แตะฐานข้อมูลจริง — สลับ settings.MONGO_DB ไปเป็น `<db>_test`
แล้วล้างทุก collection ก่อนแต่ละเทสต์ ถ้าต่อ Mongo/Redis ไม่ได้ → skip ทั้งไฟล์
(pure test ยังรันได้ตามปกติ)
"""
import asyncio
import uuid

import pytest
import pytest_asyncio
from bson import ObjectId

TEST_DB_SUFFIX = "_test"


def _drop_stale_clients() -> None:
    """ทิ้ง client ที่ผูกกับ event loop รอบก่อน โดยไม่เรียก close()

    ★ ห้าม await close_redis() ตรงนี้ — client เก่าผูกกับ loop ที่ปิดไปแล้ว
      การปิดมันจะโยน "Event loop is closed" ตั้งแต่ตอน setup fixture
      แค่ปล่อยให้ GC เก็บ แล้วสร้างใหม่บน loop ปัจจุบันพอ
    """
    from app.core import db as dbmod
    from app.core import redis_client as rmod

    if dbmod._client is not None:
        dbmod._client.close()          # motor.close() เป็น sync ไม่แตะ loop
        dbmod._client = None
    rmod._redis = None
    rmod._redis_blocking = None
    rmod._scripts.clear()              # Script object ถือ client เก่าไว้ด้วย


@pytest_asyncio.fixture
async def db():
    """Mongo test database — ล้างก่อนใช้ทุกครั้ง

    ★ ต้องปิด client เก่าก่อนทุกเทสต์: motor ผูก connection pool กับ event loop
      ที่สร้างมันขึ้นมา พอ pytest-asyncio ให้ loop ใหม่ต่อเทสต์ client เดิมจะใช้ไม่ได้
      (อาการคือ ping ค้างแล้วเทสต์ถูก skip เงียบๆ ซึ่งอันตรายกว่า fail)
    """
    from app.core import db as dbmod
    from app.core.config import settings

    if not settings.MONGO_DB.endswith(TEST_DB_SUFFIX):
        settings.MONGO_DB = settings.MONGO_DB + TEST_DB_SUFFIX

    _drop_stale_clients()
    try:
        await asyncio.wait_for(dbmod.get_client().admin.command("ping"), timeout=5)
    except Exception as e:
        pytest.skip(f"ต่อ Mongo ไม่ได้ ({e}) — docker compose up -d mongo")

    database = dbmod.get_db()
    for name in ("users", "tickets", "checkins", "coin_transactions"):
        await database[name].delete_many({})
    # unique index ที่ logic พึ่งพา — ต้องมีจริงไม่งั้นเทสต์ผ่านแบบหลอกๆ
    await database["coin_transactions"].create_index("idempotency_key", unique=True)
    await database["tickets"].create_index("user_id", unique=True)
    await database["tickets"].create_index("ticket_code", unique=True)
    yield database


@pytest_asyncio.fixture
async def redis_clean(db):
    """ล้าง key ที่เทสต์ใช้ ก่อน/หลัง — ไม่ flushall เพราะอาจมี dev data อยู่

    รับ `db` เป็น dependency เพื่อบังคับลำดับ: db จะเรียก _drop_stale_clients()
    ให้ก่อน แล้ว get_redis() ตรงนี้จึงสร้าง client บน event loop ปัจจุบัน
    """
    from app.core.redis_client import get_redis

    r = get_redis()
    try:
        await asyncio.wait_for(r.ping(), timeout=5)
    except Exception as e:
        pytest.skip(f"ต่อ Redis ไม่ได้ ({e}) — docker compose up -d redis")

    async def wipe():
        # ★ ต้องล้าง idem:* ด้วย ไม่งั้นเทสต์รอบถัดไปที่ใช้ Idempotency-Key เดิม
        #   จะได้ผลลัพธ์จาก cache กลับมาเลย โดยไม่แตะ Mongo
        #   อาการ: เทสต์ concurrency "ผ่าน" ทั้งที่ไม่ได้รันโค้ดจริงสักบรรทัด
        #   (เจอจริงตอนเขียน test_concurrent_spins — รันครั้งแรกฟ้อง ครั้งที่สองผ่านหมด)
        for pattern in ("ci:*", "checked_in:day*", "notify:last:*", "stats:checkin*",
                        "idem:*", "rl:*", "grant:*"):
            keys = [k async for k in r.scan_iter(match=pattern, count=500)]
            if keys:
                await r.delete(*keys)

    await wipe()
    yield r
    await wipe()


@pytest_asyncio.fixture
async def ticket_fixture(db, redis_clean):
    """user + บัตร 1 ใบ พร้อมเช็คอิน"""
    from datetime import datetime, timezone

    uid = ObjectId()
    now = datetime.now(timezone.utc)
    await db["users"].insert_one({
        "_id": uid, "email": f"t{uuid.uuid4().hex[:8]}@student.mahidol.ac.th",
        "display_name": "ผู้ทดสอบ", "student_id": "6913099",
        "roles": ["participant"], "status": "active", "coins_balance": 0,
        "consent": {"tos": True}, "created_at": now,
    })
    code = f"EGOKE26-{uuid.uuid4().hex[:8].upper()}"
    await db["tickets"].insert_one({
        "_id": ObjectId(), "ticket_code": code, "user_id": uid,
        "status": "issued", "tier": "general", "checked_in_days": [],
        "last_checked_in_at": None, "issued_at": now, "created_at": now,
        "schema_version": 2,
    })
    return await db["tickets"].find_one({"ticket_code": code})


@pytest.fixture
def staff_user():
    from app.core.deps import CurrentUser

    return CurrentUser(id=str(ObjectId()), roles=["staff"], jti="test-jti")
