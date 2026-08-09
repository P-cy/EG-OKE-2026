"""เทสต์ "สัญญา" ระหว่าง backend กับ frontend

บั๊กที่แพงที่สุดในโปรเจกต์นี้ไม่ใช่ logic ผิด แต่เป็น "ชื่อคีย์ไม่ตรงกัน"
และ "ชนิดข้อมูลที่ serialize ไม่ได้" — สองอย่างนี้ผ่าน type checker ทั้งคู่
แล้วไปโผล่ตอนใช้งานจริงเป็นหน้าจอว่างเปล่ากับ 500

ตัวอย่างที่เจอจริง:
  · GET /me/submissions คืนคีย์ "submissions" แต่หน้า /ig อ่าน .items
    → กล่อง "สถานะคำขอของคุณ" ขึ้นว่า "ยังไม่เคยส่ง" ตลอด
  · GET /admin/audit-logs คืน dict ที่มี ObjectId ดิบ + app ใช้ ORJSONResponse
    → 500 ทุกครั้ง ไม่เคยใช้งานได้เลยตั้งแต่เขียนมา
"""
import re
from datetime import datetime, timezone
from pathlib import Path

import orjson
import pytest
from bson import ObjectId

def _frontend_src() -> Path:
    """หา source ของ frontend — ตอนรันใน container จะถูก mount ไว้ที่ /frontend_src

    ถ้าหาไม่เจอให้ skip แทนที่จะ fail: เทสต์ชุดนี้เป็น cross-repo contract
    ไม่ควรทำให้ backend suite แดงเวลารันแยกกัน (แต่ CI ต้องเจอเสมอ)
    """
    for p in (Path("/frontend_src"), Path(__file__).resolve().parents[2] / "frontend" / "src"):
        if (p / "lib" / "api.ts").exists():
            return p
    pytest.skip("ไม่พบ source ของ frontend — mount ../frontend/src เข้ามาก่อน")


def _api_ts() -> str:
    return (_frontend_src() / "lib" / "api.ts").read_text(encoding="utf-8")


def _orjson_ok(payload) -> None:
    """ต้อง serialize ได้ด้วย orjson — คือตัวที่ app ใช้จริง (default_response_class)

    json.dumps(default=str) ผ่านแต่ orjson ไม่ผ่าน เป็นกับดักที่เจอบ่อย
    """
    orjson.dumps(payload)


# ── /me/submissions ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_my_submissions_uses_items_key(db, ticket_fixture):
    """★ คีย์ต้องเป็น "items" — ตรงกับที่ frontend อ่าน"""
    from app.core.deps import CurrentUser
    from app.routers.me import my_submissions

    uid = ticket_fixture["user_id"]
    await db["ig_submissions"].delete_many({})
    await db["ig_submissions"].insert_one({
        "user_id": uid, "shortcode": "local:aaa", "post_url": "",
        "instagram_handle": "row_one", "caption": "แคปชันใบแรก",
        "image_data": "x" * 5000, "status": "pending",
        "coins_awarded": 0, "submitted_at": datetime.now(timezone.utc),
    })

    out = await my_submissions(CurrentUser(id=str(uid), roles=["participant"], jti="j"))

    assert "items" in out, "frontend อ่าน data.items — ถ้าเปลี่ยนชื่อคีย์ หน้า /ig จะว่างเปล่าเงียบๆ"
    assert len(out["items"]) == 1
    row = out["items"][0]
    # ข้อมูลของ "ใบนั้น" ต้องมาด้วย ไม่งั้นหน้าเว็บต้องเดาจากช่องกรอก
    assert row["instagram_handle"] == "row_one"
    assert row["caption"] == "แคปชันใบแรก"
    assert "image_data" not in row, "ไม่ต้องส่ง base64 กลับมา ผู้ใช้เห็นรูปตัวเองอยู่แล้ว"
    _orjson_ok(out)


@pytest.mark.asyncio
async def test_my_submissions_key_matches_frontend_source(db):
    """กันคนแก้ backend แล้วลืมแก้ frontend (และกลับกัน)"""
    src = _api_ts()
    m = re.search(r"getMySubmissions:.*?apiFetch<\{\s*(\w+):", src, re.S)
    assert m, "หา getMySubmissions ใน api.ts ไม่เจอ"
    assert m.group(1) == "items", f"frontend อ่านคีย์ '{m.group(1)}' แต่ backend ส่ง 'items'"


# ── /admin/audit-logs ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_audit_logs_are_serializable(db):
    """★ ห้ามมี ObjectId หลุดออกไป — orjson จะพังแล้วกลายเป็น 500"""
    from app.core.deps import CurrentUser
    from app.routers.admin import audit_logs

    actor = ObjectId()
    await db["users"].insert_one({
        "_id": actor, "email": "admin@test.local", "display_name": "แอดมินทดสอบ",
        "roles": ["admin"], "status": "active", "coins_balance": 0,
    })
    await db["audit_logs"].delete_many({})
    await db["audit_logs"].insert_one({
        "actor_id": actor,
        "action": "coins.adjust",
        "target": {"type": "user", "id": str(ObjectId())},
        # ★ ของจริงเคยมี ObjectId ซ่อนใน before/after — ต้องแปลงให้หมด
        "before": {"coins_balance": 0, "ref_id": ObjectId()},
        "after": {"coins_balance": 50},
        "ip_hash": "abc",
        "user_agent": "pytest",
        "created_at": datetime.now(timezone.utc),
    })

    out = await audit_logs(CurrentUser(id=str(actor), roles=["admin"], jti="j"))

    _orjson_ok(out)
    assert "items" in out
    row = out["items"][0]
    assert row["action"] == "coins.adjust"
    assert row["actor"]["display_name"] == "แอดมินทดสอบ", "ต้อง join ชื่อมาให้ ไม่ใช่โชว์ ObjectId ดิบ"
    assert isinstance(row["before"]["ref_id"], str)


@pytest.mark.asyncio
async def test_audit_logs_filter_and_paginate(db):
    from app.core.deps import CurrentUser
    from app.routers.admin import audit_logs

    actor = ObjectId()
    await db["audit_logs"].delete_many({})
    now = datetime.now(timezone.utc)
    await db["audit_logs"].insert_many([
        {"actor_id": actor, "action": a, "target": {"type": "t", "id": "x"},
         "created_at": now, "user_agent": ""}
        for a in ("quest.create", "quest.delete", "coins.adjust", "ig.approve")
    ])
    admin = CurrentUser(id=str(actor), roles=["admin"], jti="j")

    # กรองแบบ prefix — พิมพ์ "quest" ต้องเจอทั้ง create และ delete
    only_quest = await audit_logs(admin, action="quest")
    assert {r["action"] for r in only_quest["items"]} == {"quest.create", "quest.delete"}

    # cursor: หน้าละ 2 แล้วต่อหน้าถัดไป ต้องไม่ซ้ำและไม่ข้าม
    page1 = await audit_logs(admin, limit=2)
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    page2 = await audit_logs(admin, limit=2, cursor=page1["next_cursor"])
    ids = [r["id"] for r in page1["items"]] + [r["id"] for r in page2["items"]]
    assert len(set(ids)) == 4, "หน้าถัดไปต้องไม่ซ้ำกับหน้าก่อน"


# ── datetime ต้องมี timezone ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_datetimes_from_mongo_are_timezone_aware(db):
    """★ ต้นเหตุของ "เวลาบนเว็บเพี้ยน 7 ชม."

    motor ต้องตั้ง tz_aware=True ไม่งั้นอ่านกลับมาเป็น naive datetime
    → orjson ส่งสตริงไม่มี Z → JS ตีความเป็นเวลาท้องถิ่น → คลาดไป 7 ชม.
    """
    await db["checkins"].delete_many({})
    await db["checkins"].insert_one({"at": datetime.now(timezone.utc), "result": "ok"})
    doc = await db["checkins"].find_one({"result": "ok"})

    assert doc["at"].tzinfo is not None, "ตั้ง tz_aware=True ที่ AsyncIOMotorClient"
    assert orjson.dumps(doc["at"]).decode().rstrip('"').endswith("+00:00")


# ── frontend/backend enum ต้องตรงกัน ───────────────────────────────────
def test_quest_claim_results_match_frontend_union():
    """ผลลัพธ์ที่ backend ส่งได้ ต้องมีครบใน type ฝั่ง frontend"""
    from app.models.schemas import QuestClaimOut

    backend = set(QuestClaimOut.model_fields["result"].annotation.__args__)
    src = _api_ts()
    m = re.search(r"export interface QuestClaimOut \{\s*result:\s*([^;]+);", src, re.S)
    assert m, "หา QuestClaimOut ใน api.ts ไม่เจอ"
    frontend = set(re.findall(r'"([a-z_]+)"', m.group(1)))

    assert backend == frontend, f"ไม่ตรงกัน: backend-only={backend - frontend} frontend-only={frontend - backend}"
