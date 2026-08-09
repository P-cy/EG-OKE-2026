#!/usr/bin/env python3
"""สร้าง index ทั้งหมด — รันก่อน deploy ทุกครั้ง (idempotent)

    python -m scripts.init_indexes

★ unique index หลายตัวในนี้คือด่านสุดท้ายที่กันข้อมูลเสีย
  ถ้าลืมสร้าง = โหวตซ้ำได้ / เช็คอินซ้ำได้ / ให้คะแนนซ้ำได้
"""
import asyncio
import sys

from pymongo import ASCENDING as ASC, DESCENDING as DESC

sys.path.insert(0, ".")

from app.core.db import Col, close_db, get_db  # noqa: E402


async def main() -> None:
    db = get_db()
    print(f"→ สร้าง index ใน database: {db.name}\n")

    # ── drop index ตัวเก่าที่ขัดกับ schema ใหม่ (1 ticket/user ทั้งงาน) ──
    #   uq_user_day (unique on user_id+event_day) จะกัน insert บัตรที่ 2 ของ user
    #   ix_status_day / ix_ticket_time / ix_result_time เปลี่ยน compound ใหม่
    for coll, idx in [
        ("tickets", "uq_user_day"),
        ("tickets", "ix_status_day"),
        ("checkins", "ix_ticket_time"),
        ("checkins", "ix_result_time"),
    ]:
        try:
            await db[coll].drop_index(idx)
            print(f"  · dropped {coll}.{idx}")
        except Exception:
            pass  # ยังไม่มี ก็ผ่าน

    specs: list[tuple[str, list, dict]] = [
        # users
        ("users", [("email", ASC)], {"unique": True, "name": "uq_email"}),
        ("users", [("google_sub", ASC)], {"unique": True, "sparse": True, "name": "uq_google_sub"}),
        ("users", [("student_id", ASC)], {"unique": True, "sparse": True, "name": "uq_student_id"}),
        ("users", [("coins_balance", DESC), ("_id", ASC)], {"name": "ix_coins"}),
        ("users", [("roles", ASC), ("status", ASC)], {"name": "ix_roles_status"}),

        # tickets — ★ 1 ใบต่อ user ทั้งงาน (unique user_id) + เก็บวันที่เช็คแล้วใน checked_in_days
        ("tickets", [("ticket_code", ASC)], {"unique": True, "name": "uq_ticket_code"}),
        ("tickets", [("user_id", ASC)], {"unique": True, "name": "uq_user"}),
        ("tickets", [("status", ASC)], {"name": "ix_status"}),
        ("tickets", [("checked_in_days", ASC)], {"name": "ix_checked_in_days"}),

        # checkins — ★ idempotency + ค้นประวัติรายวัน
        ("checkins", [("idempotency_key", ASC)], {"unique": True, "name": "uq_idem"}),
        ("checkins", [("ticket_id", ASC), ("event_day", ASC), ("scanned_at", DESC)],
         {"name": "ix_ticket_day_time"}),
        ("checkins", [("result", ASC), ("event_day", ASC), ("scanned_at", DESC)],
         {"name": "ix_result_day_time"}),

        # quests (บูธกิจกรรม) — ★ uq_quest_user_seq คือด่านกันรับเหรียญซ้ำ
        #   ถ้าไม่มี: staff สแกนรัว 2 ครั้ง → count ยังอ่านได้ค่าเดิม → จ่ายสองเด้ง
        ("quests", [("quest_key", ASC)], {"unique": True, "name": "uq_quest_key"}),
        ("quests", [("status", ASC), ("sort_order", ASC)], {"name": "ix_status_order"}),
        ("quest_claims", [("quest_key", ASC), ("user_id", ASC), ("seq", ASC)],
         {"unique": True, "name": "uq_quest_user_seq"}),
        ("quest_claims", [("user_id", ASC), ("claimed_at", DESC)], {"name": "ix_user_time"}),

        # artists / rounds
        ("artists", [("slug", ASC)], {"unique": True, "name": "uq_slug"}),
        ("vote_rounds", [("round_key", ASC)], {"unique": True, "name": "uq_round_key"}),
        ("vote_rounds", [("status", ASC)], {"name": "ix_status"}),

        # votes — ★ ด่านสุดท้ายกันโหวตซ้ำ (ถ้า Redis หายข้อมูล)
        ("votes", [("round_key", ASC), ("user_id", ASC)],
         {"unique": True, "name": "uq_round_user"}),
        ("votes", [("round_key", ASC), ("artist_id", ASC)], {"name": "ix_round_artist"}),

        # coins ledger — ★ หัวใจของทั้งระบบเหรียญ
        ("coin_transactions", [("idempotency_key", ASC)], {"unique": True, "name": "uq_idem"}),
        ("coin_transactions", [("user_id", ASC), ("created_at", DESC)], {"name": "ix_user_time"}),
        ("coin_transactions", [("reason", ASC), ("created_at", DESC)], {"name": "ix_reason"}),

        # instagram — ★ กันคนละคนส่งโพสต์เดียวกัน
        ("ig_submissions", [("shortcode", ASC)], {"unique": True, "name": "uq_shortcode"}),
        ("ig_submissions", [("status", ASC), ("submitted_at", ASC)], {"name": "ix_queue"}),
        ("ig_submissions", [("user_id", ASC), ("submitted_at", DESC)], {"name": "ix_user"}),

        # wheel
        ("wheel_configs", [("wheel_key", ASC)], {"unique": True, "name": "uq_wheel_key"}),
        ("wheel_spins", [("idempotency_key", ASC)], {"unique": True, "name": "uq_idem"}),
        ("wheel_spins", [("user_id", ASC), ("wheel_key", ASC), ("nonce", ASC)],
         {"unique": True, "name": "uq_user_nonce"}),

        # coin packages (topup) — admin-managed catalog
        # (ลบ coin_packages / topup_requests แล้ว — ระบบเติมเงินถูกถอดออกไปนานแล้ว
        #  ปล่อยไว้จะสร้าง collection เปล่าทุกครั้งที่รันสคริปต์)

        # audit
        ("audit_logs", [("created_at", DESC)], {"name": "ix_time"}),
        ("audit_logs", [("actor_id", ASC), ("created_at", DESC)], {"name": "ix_actor"}),

        # refresh tokens — ★ TTL index ลบเองอัตโนมัติ
        ("refresh_tokens", [("token_hash", ASC)], {"unique": True, "name": "uq_token_hash"}),
        ("refresh_tokens", [("family_id", ASC)], {"name": "ix_family"}),
        ("refresh_tokens", [("expires_at", ASC)],
         {"expireAfterSeconds": 0, "name": "ttl_expires"}),
    ]

    created, existing, failed = 0, 0, 0
    for coll_name, keys, opts in specs:
        try:
            await db[coll_name].create_index(keys, **opts)
            print(f"  ✓ {coll_name}.{opts.get('name')}")
            created += 1
        except Exception as e:
            if "already exists" in str(e) or "IndexOptionsConflict" in str(e):
                print(f"  · {coll_name}.{opts.get('name')} (มีอยู่แล้ว)")
                existing += 1
            else:
                print(f"  ✗ {coll_name}.{opts.get('name')} → {e}")
                failed += 1

    # system_config เริ่มต้น
    await Col.system_config().update_one(
        {"_id": "global"},
        {"$setOnInsert": {
            "maintenance_mode": False,
            "read_only_mode": False,
            "features": {
                "voting": True, "wheel": True, "ig_submission": True,
                "checkin": True, "leaderboard_public": True,
            },
            "announcement": {"text": "", "level": "info"},
        }},
        upsert=True,
    )
    print("\n  ✓ system_config พร้อมใช้งาน")
    print(f"\nสรุป: สร้างใหม่ {created} · มีอยู่แล้ว {existing} · ล้มเหลว {failed}")
    await close_db()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
