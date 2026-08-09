#!/usr/bin/env python3
"""Seed ข้อมูลทดสอบ — ศิลปิน, รอบโหวต, วงล้อ, user ปลอม

    python -m scripts.seed_dev            # seed พื้นฐาน
    python -m scripts.seed_dev --users 5000   # + user ปลอมสำหรับ load test
"""
import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from bson import ObjectId  # noqa: E402

from app.core.db import Col, close_db  # noqa: E402
from app.core.security import new_ticket_code  # noqa: E402
from app.services.wheel_engine import new_server_seed  # noqa: E402


async def seed_artists() -> list[ObjectId]:
    """ศิลปิน mock — รอข้อมูลจริง แล้วใช้ scripts/import_artists.py ทับได้เลย"""
    mock = [
        ("band-a", "MOCK: วงเปิดงาน"),
        ("band-b", "MOCK: วงอินดี้"),
        ("band-c", "MOCK: วงร็อก"),
        ("band-d", "MOCK: ศิลปินเดี่ยว"),
        ("band-e", "MOCK: วงปิดงาน"),
    ]
    ids = []
    for i, (slug, name) in enumerate(mock, start=1):
        doc = await Col.artists().find_one_and_update(
            {"slug": slug},
            {"$set": {"name": name, "sort_order": i, "active": True,
                      "image_url": f"https://placehold.co/400x400/1a0033/ff2d95?text={i}"},
             "$setOnInsert": {"schema_version": 1}},
            upsert=True, return_document=True,
        )
        ids.append(doc["_id"])
    print(f"  ✓ ศิลปิน mock {len(ids)} คน (ทับด้วย import_artists.py เมื่อได้ข้อมูลจริง)")
    return ids


async def seed_round(artist_ids: list[ObjectId]) -> None:
    now = datetime.now(timezone.utc)
    await Col.vote_rounds().update_one(
        {"round_key": "d1-main"},
        {"$set": {
            "title": "MOCK: โหวตศิลปินหลัก",
            "candidate_ids": artist_ids,
            "status": "open",
            "max_votes_per_user": 1,
            "opens_at": now - timedelta(hours=1),
            # ★ ไม่ตั้ง closes_at — คุมด้วยปุ่มเปิด/ปิดที่ /admin/rounds อย่างเดียว
            #   ของเดิมตั้ง +8 ชม. แล้วพอเลยเวลา รอบจะค้างสถานะ open ทั้งที่โหวตไม่ได้
            "closes_at": None,
            "results_public": True,
        }, "$setOnInsert": {"created_at": now, "schema_version": 1}},
        upsert=True,
    )
    print("  ✓ รอบโหวต d1-main (เปิดอยู่ ไม่มีเวลาปิด — ปิดเองที่ /admin/rounds)")


async def seed_quests() -> None:
    """กิจกรรมบูธ mock — admin แก้/เพิ่มเองได้ที่ /admin/quests"""
    now = datetime.now(timezone.utc)
    quests = [
        ("booth-photo", "MOCK: บูธถ่ายรูป", "ถ่ายรูปกับฉากหลัง EG'OKE แล้วให้เจ้าหน้าที่สแกนบัตร", 20, 1, 1),
        ("booth-game", "MOCK: บูธเกม", "เล่นเกมที่บูธให้จบ 1 รอบ", 30, 1, 2),
        ("booth-stamp", "MOCK: จุดแสตมป์", "แวะจุดแสตมป์ได้สูงสุด 3 ครั้งทั้งงาน", 10, 3, 3),
    ]
    for key, title, desc, coins, max_per_user, order in quests:
        await Col.quests().update_one(
            {"quest_key": key},
            {"$set": {"title": title, "description": desc, "coins": coins,
                      "status": "open", "max_per_user": max_per_user, "sort_order": order},
             "$setOnInsert": {"created_at": now, "schema_version": 1}},
            upsert=True,
        )
    print(f"  ✓ กิจกรรม mock {len(quests)} รายการ")


async def seed_wheel() -> None:
    seed, commit = new_server_seed()
    await Col.wheel_configs().update_one(
        {"wheel_key": "main-wheel"},
        {"$set": {
            "title": "วงล้อรางวัลใหญ่",
            "cost_coins": 20,
            "status": "open",
            "max_spins_per_user": 3,
            "segments": [
                {"id": "s1", "label": "เสื้อ EG'OKE", "weight": 5,
                 "stock": 20, "remaining": 20, "prize_type": "physical"},
                {"id": "s2", "label": "+100 เหรียญ", "weight": 50,
                 "remaining": None, "prize_type": "coins", "coins": 100},
                {"id": "s3", "label": "+50 เหรียญ", "weight": 200,
                 "remaining": None, "prize_type": "coins", "coins": 50},
                {"id": "s4", "label": "+10 เหรียญ", "weight": 400,
                 "remaining": None, "prize_type": "coins", "coins": 10},
                {"id": "s5", "label": "ไม่ถูกรางวัล", "weight": 345,
                 "remaining": None, "prize_type": "none"},
            ],
            "server_seed": seed,
            "commit_hash": commit,
        }, "$setOnInsert": {"schema_version": 1}},
        upsert=True,
    )
    print("  ✓ วงล้อ main-wheel")
    print(f"    commit_hash (ประกาศก่อนงานได้เลย): {commit}")


async def seed_users(n: int) -> None:
    """user ปลอมสำหรับ load test — พร้อมบัตร (1 ใบต่อคนทั้งงาน)"""
    from pymongo import InsertOne

    now = datetime.now(timezone.utc)
    batch_u, batch_t = [], []
    for i in range(n):
        uid = ObjectId()
        batch_u.append(InsertOne({
            "_id": uid,
            "email": f"loadtest{i:05d}@student.mahidol.ac.th",
            "email_domain": "student.mahidol.ac.th",
            "google_sub": f"loadtest-{i:05d}",
            "student_id": f"99{i:05d}",
            "display_name": f"Tester {i:05d}",
            "roles": ["participant"], "status": "active",
            "coins_balance": 0, "consent": {"tos": True},
            "created_at": now, "schema_version": 1,
        }))
        batch_t.append(InsertOne({
            "ticket_code": new_ticket_code(),
            "user_id": uid, "tier": "general",
            "qr_version": 1, "status": "issued",
            "checked_in_days": [],
            "last_checked_in_at": None,
            "last_checked_in_by": None,
            "last_checked_in_gate": None,
            "issued_at": now, "created_at": now, "schema_version": 2,
        }))
        if len(batch_u) >= 1000:
            await Col.users().bulk_write(batch_u, ordered=False)
            await Col.tickets().bulk_write(batch_t, ordered=False)
            batch_u, batch_t = [], []
            print(f"    ... {i + 1}/{n}")
    if batch_u:
        await Col.users().bulk_write(batch_u, ordered=False)
        await Col.tickets().bulk_write(batch_t, ordered=False)
    print(f"  ✓ user ทดสอบ {n} คน (+ บัตร)")


async def clear_loadtest_users() -> None:
    """ลบ user ปลอมทั้งหมด — ทำหลัง load test เสร็จ

    ไม่งั้นหน้า /admin/users กับ /admin/attendees จะมีคนปลอม 5,000 คนปนอยู่
    จนหาคนจริงไม่เจอตอนทดสอบหน้างาน
    """
    users = await Col.users().find({"email": {"$regex": "^loadtest"}}, {"_id": 1}).to_list(None)
    ids = [u["_id"] for u in users]
    if not ids:
        print("  · ไม่มี user ทดสอบให้ลบ")
        return
    for name, col in (("tickets", Col.tickets()), ("checkins", Col.checkins()),
                      ("votes", Col.votes()), ("coin_transactions", Col.coin_transactions()),
                      ("wheel_spins", Col.wheel_spins()), ("quest_claims", Col.quest_claims()),
                      ("ig_submissions", Col.ig_submissions())):
        res = await col.delete_many({"user_id": {"$in": ids}})
        if res.deleted_count:
            print(f"  · ลบ {name} {res.deleted_count} รายการ")
    res = await Col.users().delete_many({"_id": {"$in": ids}})
    print(f"  ✓ ลบ user ทดสอบ {res.deleted_count} คน")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--users", type=int, default=0, help="จำนวน user ปลอมสำหรับ load test")
    p.add_argument("--clear-users", action="store_true",
                   help="ลบ user ปลอมทั้งหมด (ทำหลัง load test เสร็จ) แล้วจบเลย")
    args = p.parse_args()

    if args.clear_users:
        print("→ ล้าง user ทดสอบ\n")
        await clear_loadtest_users()
        await close_db()
        return

    print("→ Seed ข้อมูลทดสอบ\n")
    artist_ids = await seed_artists()
    await seed_round(artist_ids)
    await seed_quests()
    await seed_wheel()
    if args.users:
        await seed_users(args.users)
    print("\nเสร็จแล้ว")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
