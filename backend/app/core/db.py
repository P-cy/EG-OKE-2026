"""MongoDB connection + accessor ของทุก collection"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.MONGO_URI,
            maxPoolSize=settings.MONGO_MAX_POOL,
            minPoolSize=settings.MONGO_MIN_POOL,
            # ★ timeout สั้นสำคัญมาก: ถ้า Mongo ช้า เราอยาก fail เร็วแล้วเข้า degraded mode
            #    ไม่ใช่ให้ request ค้าง 30 วิ จน connection pool หมดแล้วลามทั้งระบบ
            serverSelectionTimeoutMS=3000,
            connectTimeoutMS=3000,
            socketTimeoutMS=10000,
            retryWrites=True,
            retryReads=True,
            compressors="zstd,snappy,zlib",
            # ★ ต้องมี ไม่งั้น datetime ที่อ่านจาก Mongo กลับมาเป็น naive
            #   → orjson serialize เป็น "2026-08-07T06:11:43.548000" (ไม่มี Z/offset)
            #   → JS `new Date(...)` ตีความสตริงแบบนี้เป็น "เวลาท้องถิ่น" ตามสเปก
            #   → ทุกเวลาบนเว็บเพี้ยนไป 7 ชม. (เพิ่งส่งรูป แต่ขึ้นว่า "7 ชม.ที่แล้ว")
            tz_aware=True,
        )
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.MONGO_DB]


async def close_db() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


async def ping() -> bool:
    try:
        await get_client().admin.command("ping")
        return True
    except Exception:
        return False


# ── Collection accessors (พิมพ์ชื่อผิดจะได้รู้ตั้งแต่ import) ────────
class Col:
    @staticmethod
    def users():             return get_db()["users"]
    @staticmethod
    def tickets():           return get_db()["tickets"]
    @staticmethod
    def checkins():          return get_db()["checkins"]
    @staticmethod
    def artists():           return get_db()["artists"]
    @staticmethod
    def vote_rounds():       return get_db()["vote_rounds"]
    @staticmethod
    def votes():             return get_db()["votes"]
    @staticmethod
    def vote_tallies():      return get_db()["vote_tallies"]
    @staticmethod
    def coin_transactions(): return get_db()["coin_transactions"]
    @staticmethod
    def ig_submissions():    return get_db()["ig_submissions"]
    @staticmethod
    def wheel_configs():     return get_db()["wheel_configs"]
    @staticmethod
    def wheel_spins():       return get_db()["wheel_spins"]
    @staticmethod
    def quests():            return get_db()["quests"]
    @staticmethod
    def quest_claims():      return get_db()["quest_claims"]
    @staticmethod
    def audit_logs():        return get_db()["audit_logs"]
    @staticmethod
    def refresh_tokens():    return get_db()["refresh_tokens"]
    @staticmethod
    def system_config():     return get_db()["system_config"]
