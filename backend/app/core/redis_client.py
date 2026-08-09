"""Redis client + Lua script registry

Redis เป็น hot path ของทั้งระบบ — vote, dedupe, rate limit, leaderboard, pub/sub
"""
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

_redis: aioredis.Redis | None = None
_redis_blocking: aioredis.Redis | None = None
# หมายเหตุ: redis-py ไม่ export คลาส Script ที่ path เดียวกันทุกเวอร์ชัน
# ใช้ Any เพื่อไม่ผูกกับ internal path ที่เปลี่ยนได้
_scripts: dict[str, Any] = {}

LUA_DIR = Path(__file__).parent.parent / "lua"

# socket_timeout ของ client หลัก — ตั้งสั้นเพราะ request path ต้องล้มเร็วดีกว่าค้าง
SOCKET_TIMEOUT = 2


def get_redis() -> aioredis.Redis:
    """client หลัก สำหรับคำสั่งที่ตอบทันที (GET/SET/EVAL/PUBLISH/...)

    ⚠️ ห้ามใช้กับคำสั่งที่บล็อก (XREADGROUP BLOCK, BLPOP, BRPOP) —
       socket_timeout=2 จะตัดก่อนคำสั่งจะคืนค่า ใช้ get_redis_blocking() แทน
    """
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
            encoding="utf-8",
            decode_responses=True,
            max_connections=200,
            socket_connect_timeout=2,
            socket_timeout=SOCKET_TIMEOUT,
            health_check_interval=30,
            retry_on_timeout=True,
        )
    return _redis


def get_redis_blocking() -> aioredis.Redis:
    """client สำหรับคำสั่งที่บล็อกรอข้อมูล (worker: XREADGROUP BLOCK)

    ★ บั๊กที่เคยเจอ: worker ใช้ get_redis() ที่ socket_timeout=2 ยิง XREADGROUP BLOCK 2000ms
      → socket หมดเวลาพอดีกับตอนที่ Redis กำลังจะตอบ → "Timeout reading from redis"
      ทุกรอบ ไม่มีโหวตไหนถูกย้ายลง Mongo เลย
      client นี้ไม่ตั้ง socket_timeout (None = รอจนกว่าจะได้คำตอบ)
    """
    global _redis_blocking
    if _redis_blocking is None:
        _redis_blocking = aioredis.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
            encoding="utf-8",
            decode_responses=True,
            max_connections=10,          # worker ใช้ไม่กี่ connection
            socket_connect_timeout=2,
            socket_timeout=None,         # ★ หัวใจของการแก้
            health_check_interval=30,
        )
    return _redis_blocking


def get_script(name: str) -> Any:
    """โหลด Lua script (cache ไว้) — Redis จะ cache ด้วย SHA เอง

    Lua script ทำให้ operation หลายตัวเป็น atomic ใน round-trip เดียว
    นี่คือเหตุผลที่ /votes ทำงานได้ >20k rps
    """
    if name not in _scripts:
        src = (LUA_DIR / f"{name}.lua").read_text(encoding="utf-8")
        _scripts[name] = get_redis().register_script(src)
    return _scripts[name]


async def close_redis() -> None:
    global _redis, _redis_blocking
    if _redis is not None:
        await _redis.aclose()
        _redis = None
    if _redis_blocking is not None:
        await _redis_blocking.aclose()
        _redis_blocking = None


async def ping() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


# ── Key namespace (รวมไว้ที่เดียว กัน typo และ key ชนกัน) ────────────
class K:
    # auth
    OAUTH_STATE      = "oauth:{state}"
    JWT_DENY         = "deny:{jti}"
    # vote
    VOTE_DEDUPE      = "vote:{round}:{uid}"
    VOTE_TALLY       = "tally:{round}"
    VOTE_ZSET        = "lb:vote:{round}"
    VOTE_STREAM      = "stream:votes"
    VOTE_GROUP       = "votes-writer"
    # checkin
    CHECKIN_DEDUPE_DAY = "ci:{ticket_id}:d{day}"        # ★ per-day dedupe (1 บัตรใช้ 3 วัน)
    CHECKIN_DAY_SET    = "checked_in:day{day}"          # set ของ user_id ที่เช็คแล้วรายวัน
    CHECKIN_STATS    = "stats:checkin"
    CHECKIN_RECENT   = "stats:checkin:recent"
    CHECKIN_TS       = "stats:checkin:ts"
    # ★ กันจ่ายเหรียญซ้ำโดยไม่ตั้งใจ — กล้องอ่าน QR ใบเดิมได้เรื่อยๆ
    #   Idempotency-Key กันได้แค่ "ยิงซ้ำของ request เดียวกัน" ไม่ได้กัน "สแกนใหม่"
    #   ไม่มีตัวนี้ = ส่องกล้องค้างไว้ 10 วิ จ่ายไป 3 รอบโดยไม่มีใครรู้
    GRANT_COOLDOWN   = "grant:cd:{device}:{ticket_id}"
    # coins / leaderboard
    LB_COINS         = "lb:coins"
    LB_IG            = "lb:ig"
    USER_META        = "u:meta:{uid}"
    # live
    SNAPSHOT         = "live:snapshot"
    SEQ              = "live:seq"
    EVENTS_CHANNEL   = "live:events"
    # config
    SYS_CONFIG       = "sys:config"
    # locks
    LOCK_BROADCASTER = "lock:broadcaster"
    # idempotency
    IDEM             = "idem:{scope}:{key}"
    # per-user notify (SSE push เวลาถูกเช็คอิน + ฟอร์ม Attendance)
    #   channel จริงอยู่ที่ realtime/notify_manager.NOTIFY_CHANNEL ("notify:checkin")
    #   — channel เดียวรวม แล้ว demux ในโปรเซส (ดูเหตุผลใน notify_manager.py)
    NOTIFY_LAST      = "notify:last:{uid}"   # last payload TTL 1h (SSE reattach ตอน reconnect)
    AT_DISMISSED    = "at:dismissed:{uid}"   # suppress login re-show 1h (ปิด modal แล้วไม่เด้งซ้ำ)
