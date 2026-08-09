#!/usr/bin/env python3
"""นำเข้าศิลปิน + รอบโหวตจากไฟล์ JSON — ใช้ตอนได้ข้อมูลจริงมาแล้ว

    docker compose exec api python -m scripts.import_artists data/artists.json
    docker compose exec api python -m scripts.import_artists data/artists.json --replace

--replace = ลบศิลปินที่ไม่มีในไฟล์ออก (ระวัง: รอบโหวตที่อ้างถึงจะเสีย)
ไม่ใส่   = upsert อย่างเดียว ของเดิมที่ไม่อยู่ในไฟล์ยังอยู่

รูปแบบไฟล์ (ดูตัวอย่างที่ scripts/data/artists.example.json):
{
  "artists": [
    {"slug": "band-a", "name": "ชื่อวง", "image_url": "https://...", "sort_order": 1}
  ],
  "rounds": [
    {
      "round_key": "d1-main",
      "title": "โหวตศิลปินหลัก วันที่ 1",
      "candidates": ["band-a", "band-b"],
      "status": "closed",
      "max_votes_per_user": 1,
      "opens_at": null,
      "closes_at": null
    }
  ]
}

หมายเหตุ:
  · candidates อ้างด้วย slug ไม่ใช่ id — อ่านง่ายและแก้ไฟล์เองได้
  · status ตั้ง "closed" ไว้ก่อนได้ แล้วค่อยกดเปิดเองที่หน้า /admin/rounds ตอนขึ้นเวที
  · opens_at / closes_at เป็น null ได้ = ไม่จำกัดเวลา คุมด้วยปุ่มเปิด/ปิดล้วนๆ
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

from app.core.db import Col, close_db  # noqa: E402


def _parse_dt(v):
    if not v:
        return None
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


async def run(path: Path, replace: bool) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)

    # ── ศิลปิน ──
    slugs: list[str] = []
    for i, a in enumerate(data.get("artists", []), start=1):
        slug = a["slug"].strip().lower()
        slugs.append(slug)
        await Col.artists().update_one(
            {"slug": slug},
            {"$set": {
                "name": a["name"],
                "image_url": a.get("image_url"),
                "sort_order": a.get("sort_order", i),
                "active": a.get("active", True),
                "updated_at": now,
            },
             "$setOnInsert": {"created_at": now, "schema_version": 1}},
            upsert=True,
        )
    print(f"  · ศิลปิน upsert {len(slugs)} คน")

    if replace and slugs:
        res = await Col.artists().delete_many({"slug": {"$nin": slugs}})
        print(f"  · ลบศิลปินที่ไม่อยู่ในไฟล์ {res.deleted_count} คน")

    # slug → _id สำหรับผูกเข้ารอบโหวต
    id_by_slug = {
        a["slug"]: a["_id"]
        async for a in Col.artists().find({}, {"slug": 1})
    }

    # ── รอบโหวต ──
    for r in data.get("rounds", []):
        missing = [s for s in r.get("candidates", []) if s not in id_by_slug]
        if missing:
            print(f"  ! รอบ {r['round_key']}: ไม่พบศิลปิน slug {missing} — ข้ามคนเหล่านี้")
        candidate_ids = [id_by_slug[s] for s in r.get("candidates", []) if s in id_by_slug]

        await Col.vote_rounds().update_one(
            {"round_key": r["round_key"]},
            {"$set": {
                "title": r.get("title", r["round_key"]),
                "candidate_ids": candidate_ids,
                # ★ default เป็น closed — กันเปิดโหวตเองตั้งแต่ import
                "status": r.get("status", "closed"),
                "max_votes_per_user": r.get("max_votes_per_user", 1),
                "opens_at": _parse_dt(r.get("opens_at")),
                "closes_at": _parse_dt(r.get("closes_at")),
                "results_public": r.get("results_public", False),
                "updated_at": now,
             },
             "$setOnInsert": {"created_at": now, "schema_version": 1}},
            upsert=True,
        )
        print(f"  · รอบ {r['round_key']}: {len(candidate_ids)} คน (status={r.get('status', 'closed')})")

    print("\nเสร็จแล้ว — ไปเปิดรอบโหวตที่หน้า /admin/rounds ตอนขึ้นเวที")


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    path = Path(args[0])
    if not path.exists():
        print(f"ไม่พบไฟล์: {path}")
        sys.exit(1)
    try:
        await run(path, replace="--replace" in sys.argv)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
