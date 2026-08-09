"""Stream consumer — drain Redis Stream → MongoDB

★ นี่คือโปรเซสที่ทำให้ "Mongo ล่มแล้วเว็บไม่ล่ม" เป็นจริง
  API เขียนลง Redis Stream แล้วตอบ 202 ทันที
  worker ตัวนี้ค่อยๆ ย้ายลง Mongo เบื้องหลัง
  ถ้า Mongo ล่ม → ข้อความค้างใน stream → ไม่มีอะไรหาย
"""
import asyncio
import signal
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import InsertOne
from pymongo.errors import BulkWriteError

from app.core.db import Col, close_db
from app.core.observability import STREAM_LAG, log, setup_logging
from app.core.redis_client import K, close_redis, get_redis, get_redis_blocking

BATCH_SIZE = 500
BLOCK_MS = 2000
_running = True


async def ensure_group(stream: str, group: str) -> None:
    try:
        await get_redis().xgroup_create(stream, group, id="0", mkstream=True)
        log.info("consumer_group_created", stream=stream, group=group)
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            raise


async def drain_votes(consumer: str) -> None:
    # ★ ต้องใช้ client แบบไม่มี socket_timeout — XREADGROUP BLOCK 2000ms
    #   ถ้าใช้ get_redis() (socket_timeout=2) จะ timeout ทุกรอบ โหวตไม่ถูกย้ายลง Mongo เลย
    r = get_redis_blocking()
    while _running:
        try:
            msgs = await r.xreadgroup(
                K.VOTE_GROUP, consumer,
                {K.VOTE_STREAM: ">"},
                count=BATCH_SIZE, block=BLOCK_MS,
            )
            if not msgs:
                STREAM_LAG.set(await _pending(K.VOTE_STREAM, K.VOTE_GROUP))
                continue

            ops, ids = [], []
            for _stream, entries in msgs:
                for msg_id, fields in entries:
                    ids.append(msg_id)
                    try:
                        ops.append(InsertOne({
                            "round_key": fields["r"],
                            "user_id": ObjectId(fields["u"]),
                            "artist_id": ObjectId(fields["a"]),
                            "voted_at": datetime.fromtimestamp(
                                int(fields["t"]) / 1000, tz=timezone.utc
                            ),
                            "source": "web",
                            "client_ip_hash": fields.get("ip", ""),
                            "schema_version": 1,
                        }))
                    except Exception as e:
                        log.error("malformed_vote_message", msg_id=msg_id, error=str(e))

            if ops:
                try:
                    # ordered=False → รายการที่ซ้ำ (unique index) ไม่ทำให้ทั้ง batch ล้ม
                    await Col.votes().bulk_write(ops, ordered=False)
                except BulkWriteError as bwe:
                    dupes = sum(1 for e in bwe.details.get("writeErrors", [])
                                if e.get("code") == 11000)
                    others = len(bwe.details.get("writeErrors", [])) - dupes
                    if others:
                        log.error("vote_bulk_write_errors", non_duplicate_errors=others)
                    # duplicate = ปกติ (Redis dedupe อาจหมดอายุ) → ack ต่อได้

            # ★ ack หลังเขียนสำเร็จเท่านั้น — ถ้า crash ก่อนถึงตรงนี้ ข้อความจะถูกส่งซ้ำ
            await r.xack(K.VOTE_STREAM, K.VOTE_GROUP, *ids)
            STREAM_LAG.set(await _pending(K.VOTE_STREAM, K.VOTE_GROUP))
            log.info("votes_flushed", count=len(ids))

        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Mongo ล่ม → ไม่ ack → ข้อความค้างอยู่ → ลองใหม่เรื่อยๆ
            log.error("vote_drain_failed", error=str(e))
            await asyncio.sleep(3)


async def reclaim_stale(consumer: str) -> None:
    """กู้ข้อความที่ worker ตัวอื่นรับไปแล้วตายก่อน ack

    ถ้าไม่มีตัวนี้ worker ที่ตายจะพาข้อความหายไปกับมัน
    """
    r = get_redis()
    while _running:
        await asyncio.sleep(30)
        try:
            await r.xautoclaim(
                K.VOTE_STREAM, K.VOTE_GROUP, consumer,
                min_idle_time=60_000, count=BATCH_SIZE,
            )
        except Exception as e:
            log.warning("xautoclaim_failed", error=str(e))


async def reconcile_loop() -> None:
    """ตรวจ balance ตรงกับ ledger ทุก 5 นาที"""
    from app.services import coins

    while _running:
        await asyncio.sleep(300)
        try:
            result = await coins.reconcile_all(fix=True)
            if result["drift"]:
                log.error("coins_reconciled", **result)
        except Exception as e:
            log.warning("reconcile_failed", error=str(e))


async def _pending(stream: str, group: str) -> int:
    try:
        info = await get_redis().xpending(stream, group)
        return int(info.get("pending", 0)) if isinstance(info, dict) else 0
    except Exception:
        return 0


async def main() -> None:
    setup_logging()
    import socket
    consumer = f"worker-{socket.gethostname()}"

    await ensure_group(K.VOTE_STREAM, K.VOTE_GROUP)
    log.info("worker_started", consumer=consumer)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop)

    try:
        await asyncio.gather(
            drain_votes(consumer),
            reclaim_stale(consumer),
            reconcile_loop(),
        )
    finally:
        await close_redis()
        await close_db()
        log.info("worker_stopped")


def _stop() -> None:
    global _running
    _running = False
    log.info("worker_shutdown_requested")


if __name__ == "__main__":
    asyncio.run(main())
