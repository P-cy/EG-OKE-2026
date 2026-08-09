"""Coins ledger — append-only, idempotent

หลักการ: `users.coins_balance` เป็นแค่ cache สำหรับอ่านเร็ว
         source of truth คือผลรวมของ `coin_transactions`
ถ้าสองอย่างไม่ตรงกัน → ยึด ledger เสมอ
"""
from datetime import datetime, timezone

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.db import Col
from app.core.redis_client import K, get_redis
from app.core.observability import COINS_DRIFT, log


class CoinsResult:
    def __init__(
        self, awarded: bool, balance: int, tx_id: str | None = None,
        insufficient: bool = False,
    ):
        self.awarded = awarded
        self.balance = balance
        self.tx_id = tx_id
        self.insufficient = insufficient   # หักไม่ได้เพราะเหรียญไม่พอ (ไม่ใช่ "ให้ไปแล้ว")


async def spend(
    user_id: ObjectId,
    amount: int,
    reason: str,
    idempotency_key: str,
    ref: dict | None = None,
    note: str = "",
) -> CoinsResult:
    """หักเหรียญแบบ atomic — กันยอดติดลบ

    ★ ทำไมต้องมีตัวนี้แยกจาก award():
      โค้ดเดิมทำ `balance_of()` แล้วค่อย `award(-cost)` ซึ่งเป็น TOCTOU —
      ยิงพร้อมกัน 2 request ผ่านด่านเช็คทั้งคู่ แล้วหักทั้งคู่ → ยอดติดลบ
      (กดปุ่มรัวๆ ตอนเน็ตช้าก็เกิดได้ ไม่ต้องตั้งใจโกง)

    ตัวนี้หักด้วย update ที่มีเงื่อนไข `coins_balance >= amount` ใน query เดียว
    Mongo รับประกัน atomic ต่อ document → เกินยอดไม่ผ่านแน่นอน

    amount ต้องเป็นจำนวนบวก (จำนวนที่จะหัก)
    """
    if amount <= 0:
        raise ValueError("spend() รับ amount เป็นจำนวนบวกเท่านั้น")

    now = datetime.now(timezone.utc)

    # ── 1. หักแบบมีเงื่อนไข — ด่านเดียวที่เชื่อถือได้ ──
    updated = await Col.users().find_one_and_update(
        {"_id": user_id, "coins_balance": {"$gte": amount}},
        {"$inc": {"coins_balance": -amount}, "$set": {"coins_updated_at": now}},
        projection={"coins_balance": 1},
        return_document=True,
    )
    if updated is None:
        user = await Col.users().find_one({"_id": user_id}, {"coins_balance": 1})
        return CoinsResult(False, (user or {}).get("coins_balance", 0), insufficient=True)

    balance = updated.get("coins_balance", 0)

    # ── 2. บันทึก ledger ──
    try:
        res = await Col.coin_transactions().insert_one({
            "idempotency_key": idempotency_key,
            "user_id": user_id,
            "amount": -amount,
            "balance_after": balance,
            "reason": reason,
            "ref": ref or {},
            "actor_id": None,
            "note": note,
            "created_at": now,
            "schema_version": 1,
        })
    except DuplicateKeyError:
        # เคยหักไปแล้วด้วย key นี้ (ยิงซ้ำ) → คืนที่เพิ่งหักไป ไม่หักสองเด้ง
        refunded = await Col.users().find_one_and_update(
            {"_id": user_id},
            {"$inc": {"coins_balance": amount}},
            projection={"coins_balance": 1},
            return_document=True,
        )
        return CoinsResult(False, (refunded or {}).get("coins_balance", 0))

    try:
        await get_redis().zincrby(K.LB_COINS, -amount, str(user_id))
    except Exception:
        log.warning("leaderboard_sync_failed", user_id=str(user_id))

    return CoinsResult(True, balance, str(res.inserted_id))


async def award(
    user_id: ObjectId,
    amount: int,
    reason: str,
    idempotency_key: str,
    ref: dict | None = None,
    actor_id: ObjectId | None = None,
    note: str = "",
) -> CoinsResult:
    """ให้/หักเหรียญแบบ idempotent

    ⚠️ ไม่กันยอดติดลบ — ถ้าเป็นการ "จ่ายเพื่อซื้อของ" ให้ใช้ spend() แทน
       (ตัวนี้ยังต้องรับ amount ติดลบได้ สำหรับ admin ปรับยอดแบบตั้งใจ)

    ลำดับสำคัญมาก:
      1. จอง idempotency_key ก่อน (unique index จะปฏิเสธถ้าซ้ำ)
      2. แล้วค่อย $inc balance

    ถ้าสลับลำดับแล้วโปรเซสตายกลางทาง → ผู้ใช้ได้เหรียญซ้ำ
    ลำดับนี้ worst case คือ ledger มีแต่ balance ยังไม่อัปเดต
    ซึ่ง job reconcile ทุก 5 นาทีจะซ่อมให้เอง (ปลอดภัยกว่า)
    """
    now = datetime.now(timezone.utc)

    try:
        res = await Col.coin_transactions().insert_one(
            {
                "idempotency_key": idempotency_key,
                "user_id": user_id,
                "amount": amount,
                "balance_after": None,  # เติมทีหลัง
                "reason": reason,
                "ref": ref or {},
                "actor_id": actor_id,
                "note": note,
                "created_at": now,
                "schema_version": 1,
            }
        )
    except DuplicateKeyError:
        # เคยให้ไปแล้ว — ไม่ใช่ error, คืนยอดปัจจุบัน
        user = await Col.users().find_one({"_id": user_id}, {"coins_balance": 1})
        return CoinsResult(False, (user or {}).get("coins_balance", 0))

    updated = await Col.users().find_one_and_update(
        {"_id": user_id},
        {"$inc": {"coins_balance": amount}, "$set": {"coins_updated_at": now}},
        projection={"coins_balance": 1},
        return_document=True,
    )
    balance = (updated or {}).get("coins_balance", 0)

    await Col.coin_transactions().update_one(
        {"_id": res.inserted_id}, {"$set": {"balance_after": balance}}
    )

    # sync leaderboard (ไม่ critical — ถ้าพลาด job reconcile จะซ่อม)
    try:
        await get_redis().zincrby(K.LB_COINS, amount, str(user_id))
    except Exception:
        log.warning("leaderboard_sync_failed", user_id=str(user_id))

    return CoinsResult(True, balance, str(res.inserted_id))


async def balance_of(user_id: ObjectId) -> int:
    user = await Col.users().find_one({"_id": user_id}, {"coins_balance": 1})
    return (user or {}).get("coins_balance", 0)


async def ledger_sum(user_id: ObjectId) -> int:
    """ผลรวมจริงจาก ledger — ใช้ตอน reconcile"""
    cursor = Col.coin_transactions().aggregate(
        [{"$match": {"user_id": user_id}}, {"$group": {"_id": None, "s": {"$sum": "$amount"}}}]
    )
    docs = await cursor.to_list(1)
    return docs[0]["s"] if docs else 0


async def reconcile_all(fix: bool = True) -> dict:
    """ตรวจว่า balance ตรงกับ ledger ไหม — รันทุก 5 นาที

    ถ้า drift > 0 แปลว่ามีบั๊กหรือมีโปรเซสตายกลางทาง → ต้องได้ alert
    """
    pipeline = [
        {"$group": {"_id": "$user_id", "ledger": {"$sum": "$amount"}}},
    ]
    drift, fixed = 0, 0
    async for row in Col.coin_transactions().aggregate(pipeline):
        uid, expected = row["_id"], row["ledger"]
        user = await Col.users().find_one({"_id": uid}, {"coins_balance": 1})
        if not user:
            continue
        actual = user.get("coins_balance", 0)
        if actual != expected:
            drift += 1
            log.error(
                "coins_drift_detected",
                user_id=str(uid), balance=actual, ledger=expected,
            )
            if fix:
                await Col.users().update_one(
                    {"_id": uid}, {"$set": {"coins_balance": expected}}
                )
                await get_redis().zadd(K.LB_COINS, {str(uid): expected})
                fixed += 1

    COINS_DRIFT.set(drift)
    return {"drift": drift, "fixed": fixed}


async def rebuild_leaderboard() -> int:
    """สร้าง Redis leaderboard ใหม่จาก Mongo — ใช้ตอน Redis หายข้อมูล"""
    r = get_redis()
    pipe = r.pipeline()
    pipe.delete(K.LB_COINS)
    count = 0
    async for u in Col.users().find(
        {"coins_balance": {"$gt": 0}}, {"coins_balance": 1}
    ):
        pipe.zadd(K.LB_COINS, {str(u["_id"]): u["coins_balance"]})
        count += 1
        if count % 500 == 0:
            await pipe.execute()
            pipe = r.pipeline()
    await pipe.execute()
    log.info("leaderboard_rebuilt", users=count)
    return count
