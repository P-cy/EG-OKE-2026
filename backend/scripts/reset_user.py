"""ลบ user 1 คนออกจากระบบทั้งหมด เพื่อทดสอบตั้งแต่หน้า login ใหม่

ใช้ตอนอยากเห็นกระบวนการเต็ม: login Google -> onboarding -> ออกบัตร -> เช็คอิน

    docker compose exec api python -m scripts.reset_user <email>
    docker compose exec api python -m scripts.reset_user <email> --checkin-only

--checkin-only = เก็บ user/บัตรไว้ ล้างแค่สถานะเช็คอิน+เหรียญ (เทสต์สแกนซ้ำเร็วๆ)

ลบอะไรบ้าง (โหมดเต็ม):
  Mongo  users, tickets, checkins, coin_transactions, refresh_tokens,
         votes, ig_submissions, wheel_spins, audit_logs (ที่ actor เป็นคนนี้)
  Redis  ci:*(บัตรนี้), notify:last:*, at:dismissed:*, user:meta:*,
         idem ของ coin, leaderboard members, checked_in:day*
"""
import asyncio
import sys

from app.core.db import Col, close_db
from app.core.redis_client import K, close_redis, get_redis


async def reset(email: str, checkin_only: bool = False) -> None:
    user = await Col.users().find_one({"email": email})
    if not user:
        print(f"ไม่พบ user: {email}")
        return

    uid = user["_id"]
    print(f"เจอ user: {email}  id={uid}")
    r = get_redis()

    # ── บัตร + สถานะเช็คอิน ──
    tickets = await Col.tickets().find({"user_id": uid}).to_list(10)
    for t in tickets:
        for day in (1, 2, 3):
            await r.delete(K.CHECKIN_DEDUPE_DAY.format(ticket_id=str(t["_id"]), day=day))
            await r.srem(K.CHECKIN_DAY_SET.format(day=day), str(uid))
        print(f"  · ล้าง dedupe ของบัตร {t['ticket_code']}")

    n = (await Col.checkins().delete_many({"ticket_id": {"$in": [t["_id"] for t in tickets]}})).deleted_count
    print(f"  · ลบ checkins {n} แถว")

    n = (await Col.coin_transactions().delete_many({"user_id": uid})).deleted_count
    print(f"  · ลบ coin_transactions {n} แถว")

    # ── key ราย user ที่ต้องหายทุกโหมด ──
    for key in (
        K.NOTIFY_LAST.format(uid=str(uid)),
        K.AT_DISMISSED.format(uid=str(uid)),
        K.USER_META.format(uid=str(uid)),
    ):
        await r.delete(key)
    await r.zrem(K.LB_COINS, str(uid))
    await r.zrem(K.LB_IG, str(uid))

    if checkin_only:
        # เก็บ user + บัตรไว้ ล้างแค่สถานะ
        await Col.tickets().update_many(
            {"user_id": uid},
            {"$set": {"checked_in_days": [], "last_checked_in_at": None,
                      "last_checked_in_by": None, "last_checked_in_gate": None}},
        )
        await Col.users().update_one({"_id": uid}, {"$set": {"coins_balance": 0}})
        print("เรียบร้อย (checkin-only) — บัตรเดิมยังใช้ได้ เหรียญกลับเป็น 0")
        return

    # ── โหมดเต็ม: ลบทุกอย่างของคนนี้ ──
    for name, coll, q in (
        ("tickets",        Col.tickets(),        {"user_id": uid}),
        ("refresh_tokens", Col.refresh_tokens(), {"user_id": uid}),
        ("votes",          Col.votes(),          {"user_id": uid}),
        ("ig_submissions", Col.ig_submissions(), {"user_id": uid}),
        ("wheel_spins",    Col.wheel_spins(),    {"user_id": uid}),
        ("audit_logs",     Col.audit_logs(),     {"actor_id": uid}),
    ):
        n = (await coll.delete_many(q)).deleted_count
        print(f"  · ลบ {name} {n} แถว")

    await Col.users().delete_one({"_id": uid})
    print("  · ลบ user")
    print()
    print("เรียบร้อย — ล็อกอินใหม่จะถือเป็นคนใหม่ (needs_onboarding = true)")
    print("อย่าลืมล้างฝั่งเบราว์เซอร์ด้วย: เปิด Console แล้วพิมพ์")
    print("    localStorage.clear(); location.href='/login'")


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    try:
        await reset(args[0], checkin_only="--checkin-only" in sys.argv)
    finally:
        await close_redis()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
