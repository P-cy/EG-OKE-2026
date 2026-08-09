"""Snapshot broadcaster — singleton

สร้าง live:snapshot ทุก 1 วินาที แล้ว publish ให้ WebSocket
★ ต้องมีตัวเดียวเท่านั้น — ใช้ Redis lock กันรันซ้อน

ผลลัพธ์: endpoint GET /live/snapshot แค่ GET จาก Redis ไม่คำนวณอะไรเลย
         → รับ 667 rps ได้ด้วย CPU แทบเป็นศูนย์
"""
import asyncio
import json
import os
import signal
from datetime import datetime, timezone

from bson import ObjectId

from app.core.config import settings
from app.core.db import Col, close_db
from app.core.observability import log, setup_logging
from app.core.redis_client import K, close_redis, get_redis

INSTANCE = f"bc-{os.getpid()}-{os.urandom(4).hex()}"
LOCK_TTL_MS = 3000
_running = True


async def acquire_lock() -> bool:
    return bool(await get_redis().set(K.LOCK_BROADCASTER, INSTANCE, nx=True, px=LOCK_TTL_MS))


async def renew_lock() -> bool:
    """renew เฉพาะถ้ายังเป็นเจ้าของ lock (Lua = atomic check-and-set)"""
    script = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
      return redis.call('PEXPIRE', KEYS[1], ARGV[2])
    end
    return 0
    """
    return bool(await get_redis().eval(script, 1, K.LOCK_BROADCASTER, INSTANCE, LOCK_TTL_MS))


async def build_snapshot() -> dict:
    r = get_redis()
    seq = await r.incr(K.SEQ)
    now = datetime.now(timezone.utc)

    # ── รอบโหวตที่เปิดอยู่ ──
    active = None
    rnd = await Col.vote_rounds().find_one({"status": "open"})
    if rnd:
        rk = rnd["round_key"]
        tally = await r.hgetall(K.VOTE_TALLY.format(round=rk))
        names = {
            str(a["_id"]): a.get("name", "?")
            async for a in Col.artists().find(
                {"_id": {"$in": [ObjectId(x) for x in tally]}}, {"name": 1}
            )
        }
        closes_in = None
        if rnd.get("closes_at"):
            ca = rnd["closes_at"]
            ca = ca if ca.tzinfo else ca.replace(tzinfo=timezone.utc)
            closes_in = max(0, int((ca - now).total_seconds()))

        active = {
            "round_key": rk,
            "title": rnd.get("title", ""),
            "status": rnd["status"],
            "closes_in": closes_in,
            "results_public": bool(rnd.get("results_public")),
            # ★ ซ่อนตัวเลขจริงถ้ายังไม่เปิดผล (กัน bandwagon effect)
            "tally": sorted(
                (
                    {"artist_id": aid, "name": names.get(aid, "?"), "votes": int(v)}
                    for aid, v in tally.items()
                ),
                key=lambda x: -x["votes"],
            ) if rnd.get("results_public") else [],
            "total_votes": sum(int(v) for v in tally.values()),
        }

    # ── check-in stats ──
    stats = await r.hgetall(K.CHECKIN_STATS)
    rate = await r.zcount(K.CHECKIN_TS, now.timestamp() - 60, now.timestamp())

    # ── leaderboards ──
    # ★ ถอด top_coins ออกแล้ว — ไม่มีหน้าอันดับ coin ทั้งฝั่งผู้ใช้และจอใหญ่
    #   snapshot ถูกสร้างใหม่ทุก 1 วิ การดึง zset + USER_META 10 คนทุกวินาที
    #   โดยไม่มีใครแสดงผลคือ Redis round-trip ทิ้งเปล่า 11 ครั้ง/วิ
    top_ig = await _top(K.LB_IG, 10)

    # ── config ──
    cfg_doc = await Col.system_config().find_one({"_id": "global"}) or {}

    return {
        "server_time": now.isoformat(),
        "seq": seq,
        "active_round": active,
        "checkins": {
            "today": int(stats.get("today", 0)),
            "rate_per_min": int(rate),
            "gates": {
                k.replace("gate:", ""): int(v)
                for k, v in stats.items() if k.startswith("gate:")
            },
        },
        "top_ig": top_ig,
        "announcement": cfg_doc.get("announcement", {"text": "", "level": "info"}),
        "features": cfg_doc.get("features", {}),
    }


async def _top(key: str, n: int) -> list[dict]:
    r = get_redis()
    rows = await r.zrevrange(key, 0, n - 1, withscores=True)
    out = []
    for rank, (uid, score) in enumerate(rows, start=1):
        raw = await r.get(K.USER_META.format(uid=uid))
        meta = json.loads(raw) if raw else {}
        out.append({
            "rank": rank,
            "display_name": meta.get("display_name", "ผู้เข้าร่วม"),
            "avatar_url": meta.get("avatar_url"),
            "instagram_handle": meta.get("instagram_handle"),
            "score": int(score),
        })
    return out


async def persist_tallies() -> None:
    """เขียน tally ลง Mongo ทุก 10 วิ — ใช้กู้ Redis ถ้าหายข้อมูล"""
    r = get_redis()
    async for rnd in Col.vote_rounds().find({"status": "open"}):
        rk = rnd["round_key"]
        tally = await r.hgetall(K.VOTE_TALLY.format(round=rk))
        if not tally:
            continue
        await Col.vote_tallies().update_one(
            {"_id": rk},
            {"$set": {
                "tally": {k: int(v) for k, v in tally.items()},
                "total": sum(int(v) for v in tally.values()),
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )


async def main() -> None:
    setup_logging()
    log.info("broadcaster_starting", instance=INSTANCE)
    r = get_redis()
    interval = settings.SNAPSHOT_INTERVAL_MS / 1000
    tick = 0

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop)

    try:
        while _running:
            # ── ต้องถือ lock ถึงจะทำงาน (กันรันซ้อนตอน deploy) ──
            if not await renew_lock():
                if not await acquire_lock():
                    await asyncio.sleep(1)
                    continue
                log.info("broadcaster_lock_acquired", instance=INSTANCE)

            try:
                snap = await build_snapshot()
                payload = json.dumps(snap, default=str)
                # ex=30 → ถ้า broadcaster ตาย snapshot จะ stale ไม่เกิน 30 วิ แล้วหาย
                # (ดีกว่าปล่อยให้ค้างแสดงข้อมูลเก่าไปเรื่อยๆ)
                await r.set(K.SNAPSHOT, payload, ex=30)
                await r.publish(
                    K.EVENTS_CHANNEL, json.dumps({"type": "snapshot", "data": snap}, default=str)
                )

                tick += 1
                if tick % 10 == 0:
                    await persist_tallies()

            except Exception as e:
                log.error("snapshot_build_failed", error=str(e))

            await asyncio.sleep(interval)
    finally:
        await close_redis()
        await close_db()
        log.info("broadcaster_stopped")


def _stop() -> None:
    global _running
    _running = False


if __name__ == "__main__":
    asyncio.run(main())
