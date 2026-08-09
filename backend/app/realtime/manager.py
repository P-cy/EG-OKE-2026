"""WebSocket connection manager + Redis Pub/Sub fanout

จอแสดงผลหน้างาน (5-10 ตัว) เท่านั้นที่ใช้ WS
มือถือผู้เข้าร่วม (2,000 ตัว) ใช้ HTTP polling — ดู docs/04-realtime.md
"""
import asyncio
import json
from dataclasses import dataclass, field

from fastapi import WebSocket

from app.core.config import settings
from app.core.observability import WS_CONNS, log
from app.core.redis_client import K, get_redis


@dataclass
class Conn:
    ws: WebSocket
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=200))
    channels: set[str] = field(default_factory=set)
    alive: bool = True


class Manager:
    def __init__(self) -> None:
        self._conns: set[Conn] = set()
        self._pubsub_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._pubsub_task is None:
            self._pubsub_task = asyncio.create_task(self._pump())
            log.info("ws_manager_started")

    async def stop(self) -> None:
        if self._pubsub_task:
            self._pubsub_task.cancel()
            self._pubsub_task = None

    async def connect(self, ws: WebSocket) -> Conn:
        await ws.accept()
        conn = Conn(ws=ws)
        self._conns.add(conn)
        WS_CONNS.set(len(self._conns))
        return conn

    def disconnect(self, conn: Conn) -> None:
        conn.alive = False
        self._conns.discard(conn)
        WS_CONNS.set(len(self._conns))

    async def _pump(self) -> None:
        """SUBSCRIBE ครั้งเดียวต่อ worker แล้ว fanout ให้ connection ในตัวเอง

        → Redis เห็นแค่ 1 subscriber ต่อ worker ไม่ว่าจะมีกี่จอ
        """
        r = get_redis()
        pubsub = r.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(K.EVENTS_CHANNEL)
        log.info("ws_pubsub_subscribed", channel=K.EVENTS_CHANNEL)

        try:
            async for msg in pubsub.listen():
                if msg is None or msg.get("type") != "message":
                    continue
                self.broadcast(msg["data"])
        except asyncio.CancelledError:
            await pubsub.unsubscribe(K.EVENTS_CHANNEL)
            raise
        except Exception as e:
            log.error("ws_pubsub_failed", error=str(e))
            await asyncio.sleep(2)
            # restart ตัวเอง
            self._pubsub_task = asyncio.create_task(self._pump())

    def broadcast(self, payload: str) -> None:
        """★ backpressure: client ช้า → ตัดทิ้ง

        ถ้าไม่ทำ queue จะบวมจน RAM หมดแล้วโปรเซสตาย
        จอ Raspberry Pi เก่าๆ ทำแบบนี้ได้จริง
        """
        dead = []
        for conn in self._conns:
            if not conn.alive:
                dead.append(conn)
                continue
            if conn.queue.qsize() > settings.WS_MAX_QUEUE:
                log.warning("ws_slow_consumer_dropped", qsize=conn.queue.qsize())
                conn.alive = False
                dead.append(conn)
                continue
            try:
                conn.queue.put_nowait(payload)
            except asyncio.QueueFull:
                conn.alive = False
                dead.append(conn)
        for c in dead:
            self.disconnect(c)

    async def sender(self, conn: Conn) -> None:
        """ส่งข้อความจาก queue + heartbeat"""
        try:
            while conn.alive:
                try:
                    payload = await asyncio.wait_for(
                        conn.queue.get(), timeout=settings.WS_HEARTBEAT_SECONDS
                    )
                    await conn.ws.send_text(payload)
                except asyncio.TimeoutError:
                    await conn.ws.send_text(json.dumps({"type": "ping"}))
        except Exception:
            conn.alive = False

    @property
    def count(self) -> int:
        return len(self._conns)


manager = Manager()
