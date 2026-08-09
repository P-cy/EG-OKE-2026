"""Per-user notify fanout — SSE push สำหรับมือถือคนเข้างาน

★ ปัญหา: ถ้าแต่ละ SSE ของแต่ละคน SUBSCRIBE channel ของตัวเอง → ใช้ 1 Redis connection ต่อคน
  งาน 500+ คนเปิดแอปพร้อมกัน → Redis pool (200) พัง → SSE ต่อใหม่ไม่ได้

★ ทางแก้: singleton ตัวเดียว SUBSCRIBE channel เดียว `notify:checkin` (1 Redis connection ตลอด)
  route ข้อความไปยัง queue ของแต่ละ user (dict[uid, asyncio.Queue])
  SSE แต่ละคนแค่อ่าน queue ของตัวเอง → ใช้ Redis connection ไม่เพิ่มตามจำนวนคน

  backpressure: queue เต็ม → ทิ้งข้อความเก่า (SSE แค่ push ล่าสุด ไม่ critical)
"""
import asyncio
import json
from dataclasses import dataclass, field

from app.core.observability import log
from app.core.redis_client import get_redis

# channel กลางเดียว — publish ทุก checkin_ok มาที่นี่ (payload มี uid อยู่ข้างใน)
NOTIFY_CHANNEL = "notify:checkin"


@dataclass
class _Sub:
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=8))


class NotifyManager:
    """singleton — 1 Redis pubsub connection, fanout ไปยัง queue ราย user"""

    def __init__(self) -> None:
        self._subs: dict[str, _Sub] = {}          # uid → Sub
        self._pubsub_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._pubsub_task is None:
            self._pubsub_task = asyncio.create_task(self._pump())
            log.info("notify_manager_started")

    async def stop(self) -> None:
        if self._pubsub_task:
            self._pubsub_task.cancel()
            self._pubsub_task = None
        self._subs.clear()

    def subscribe(self, uid: str) -> _Sub:
        sub = self._subs.get(uid)
        if sub is None:
            sub = _Sub()
            self._subs[uid] = sub
        return sub

    def unsubscribe(self, uid: str, sub: _Sub) -> None:
        # มี sub ใหม่มาแทนที่ → อย่าลบของใหม่
        if self._subs.get(uid) is sub:
            self._subs.pop(uid, None)

    async def _pump(self) -> None:
        """SUBSCRIBE channel เดียว → route ข้อความไป queue ของ user ที่เกี่ยวข้อง"""
        r = get_redis()
        pubsub = r.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(NOTIFY_CHANNEL)
        log.info("notify_pubsub_subscribed", channel=NOTIFY_CHANNEL)

        try:
            async for msg in pubsub.listen():
                if msg is None or msg.get("type") != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                    uid = data.get("uid")
                except Exception:
                    continue
                if not uid:
                    continue
                sub = self._subs.get(uid)
                if not sub:
                    continue  # ไม่มีใครเปิด SSE อยู่ → ไม่ต้องเก็บ (มี NOTIFY_LAST ใน Redis อยู่แล้ว)
                # backpressure: queue เต็ม → ทิ้งข้อความเก่า เก็บล่าสุด
                try:
                    sub.queue.put_nowait(msg["data"])
                except asyncio.QueueFull:
                    try:
                        sub.queue.get_nowait()
                        sub.queue.put_nowait(msg["data"])
                    except Exception:
                        pass
        except asyncio.CancelledError:
            await pubsub.unsubscribe(NOTIFY_CHANNEL)
            raise
        except Exception as e:
            log.error("notify_pubsub_failed", error=str(e))
            await asyncio.sleep(2)
            # restart ตัวเอง
            self._pubsub_task = asyncio.create_task(self._pump())

    @property
    def count(self) -> int:
        return len(self._subs)


notify_manager = NotifyManager()
