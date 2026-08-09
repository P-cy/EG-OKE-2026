"""Admin API — ทุก action ถูกบันทึกใน audit_logs โดยไม่มีข้อยกเว้น"""
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.db import Col
from app.core.deps import CurrentUser, require_admin
from app.core.errors import bad_request, conflict, not_found
from app.core.redis_client import K, get_redis
from app.models.schemas import (
    CheckinOut, ConfigPatchIn, CoinAdjustIn, ManualCheckinIn,
    QuestIn, QuestPatch, QuestPublic, UserRolesIn,
)
from app.routers.checkin import checkin_core
from app.routers.ig import WALL_COST as IG_WALL_COST
from app.services import coins, grant_limits
from app.services.attendance import query_attendees
from app.services.audit import audit

router = APIRouter(prefix="/admin", tags=["admin"])
AdminDep = Annotated[CurrentUser, Depends(require_admin)]


@router.get("/dashboard")
async def dashboard(admin: AdminDep):
    r = get_redis()
    stats = await r.hgetall(K.CHECKIN_STATS)
    return {
        "users": {
            "total": await Col.users().count_documents({}),
            "active": await Col.users().count_documents({"status": "active"}),
        },
        "checkins": {
            "today": int(stats.get("today", 0)),
            "total": await Col.checkins().count_documents({"result": "ok"}),
        },
        "votes": {
            "total": await Col.votes().count_documents({}),
            "stream_pending": await r.xlen(K.VOTE_STREAM),
        },
        "ig": {
            "pending": await Col.ig_submissions().count_documents({"status": "pending"}),
            "approved": await Col.ig_submissions().count_documents({"status": "approved"}),
        },
        "spins": await Col.wheel_spins().count_documents({}),
        "as_of": datetime.now(timezone.utc),
    }


@router.get("/users")
async def list_users(admin: AdminDep, q: str = "", limit: int = 50, cursor: str | None = None):
    query: dict = {}
    if q:
        # ★ escape regex — ไม่งั้นผู้ใช้ส่ง ".*" มาก็ scan ทั้ง collection
        safe = re.escape(q)
        query["$or"] = [
            {"email": {"$regex": safe, "$options": "i"}},
            {"display_name": {"$regex": safe, "$options": "i"}},
            # ★ ต้องหาด้วยชื่อจริงได้ด้วย — เปิดรับอีเมลทุก domain แล้ว
            #   อีเมลไม่ได้บอกว่าใครเป็นใครอีกต่อไป และคนนอกมหิดลไม่มีรหัสนักศึกษา
            {"full_name": {"$regex": safe, "$options": "i"}},
            {"student_id": {"$regex": safe}},
        ]
    if cursor:
        query["_id"] = {"$gt": ObjectId(cursor)}

    rows = await Col.users().find(query).sort("_id", 1).to_list(min(limit, 200))
    return {
        "users": [
            {
                "id": str(u["_id"]), "email": u["email"],
                "display_name": u.get("display_name"),
                "student_id": u.get("student_id"),
                "roles": u.get("roles", []), "status": u.get("status"),
                "coins_balance": u.get("coins_balance", 0),
            }
            for u in rows
        ],
        "next_cursor": str(rows[-1]["_id"]) if len(rows) == min(limit, 200) else None,
    }


@router.post("/users/{user_id}/points")
async def adjust_points(user_id: str, body: CoinAdjustIn, admin: AdminDep, request: Request):
    oid = ObjectId(user_id)
    before = await coins.balance_of(oid)

    # idempotency key ผูกกับเวลา — admin กดสองครั้งเร็วๆ ได้แค่ครั้งเดียว
    key = f"admin:{admin.id}:{user_id}:{int(datetime.now(timezone.utc).timestamp())}"
    res = await coins.award(
        user_id=oid, amount=body.amount, reason=body.reason,
        idempotency_key=key, actor_id=admin.oid, note=body.note,
    )
    await audit(request, admin, "coins.adjust", "user", user_id,
                {"coins_balance": before}, {"coins_balance": res.balance})
    return {"transaction_id": res.tx_id, "new_balance": res.balance}


@router.post("/users/{user_id}/roles")
async def set_user_roles(user_id: str, body: UserRolesIn, admin: AdminDep, request: Request):
    """ตั้งสิทธิ์ให้ผู้ใช้ — participant / staff / admin

    ★ role ฝังอยู่ใน access token (อายุ 15 นาที) ไม่ได้อ่านจาก DB ทุก request
      แปลว่าคนที่เพิ่งได้ role จะยังใช้ไม่ได้จนกว่า token จะรอบใหม่
      endpoint นี้จึงตอบ `takes_effect` กลับไปให้หน้าเว็บบอก admin ตรงๆ
      ว่าต้องให้คนนั้นออกแล้วล็อกอินใหม่ ไม่ใช่ปล่อยให้งงว่าทำไมยังเข้าไม่ได้
    """
    oid = ObjectId(user_id)
    target = await Col.users().find_one({"_id": oid}, {"roles": 1, "display_name": 1, "email": 1})
    if not target:
        raise not_found("ผู้ใช้")

    before = target.get("roles", [])
    # participant ติดมากับทุกคนเสมอ — ถอดออกแล้วเจ้าตัวใช้หน้าผู้ใช้ไม่ได้
    after = sorted({"participant", *body.roles})

    # ★ ห้ามถอด admin ของตัวเอง — ล็อกตัวเองออกจากระบบกลางงานแล้วไม่มีใครแก้ให้
    if admin.id == user_id and "admin" not in after:
        raise bad_request(
            "CANNOT_DEMOTE_SELF",
            "ถอดสิทธิ์ admin ของตัวเองไม่ได้ — ให้ admin คนอื่นเป็นคนถอดให้",
        )

    await Col.users().update_one({"_id": oid}, {"$set": {"roles": after}})
    await audit(request, admin, "user.roles", "user", user_id, {"roles": before}, {"roles": after})
    return {
        "ok": True,
        "roles": after,
        "takes_effect": "ให้คนนี้กดออกจากระบบแล้วล็อกอินใหม่ สิทธิ์ถึงจะมีผลทันที "
                        "(ถ้าไม่ทำอะไร จะมีผลเองภายใน 15 นาที)",
    }


@router.get("/grants/summary")
async def grants_summary(admin: AdminDep, hours: int = 24, top: int = 15):
    """เฝ้าดูการจ่ายเหรียญของ staff — หน้าที่ใช้จับความผิดปกติจริง

    ★ โควตากันได้แค่ "จ่ายเยอะเกินไป" แต่กัน "จ่ายพอดีๆ ให้คนเดิมทุกวัน" ไม่ได้
      สิ่งที่จับได้คือ **รูปแบบ** — คู่ staff/ผู้รับที่จ่ายกันบ่อยผิดปกติ
      ตัวเลขดิบไม่บอกอะไร ต้องเรียงให้เห็นว่าใครโดดจากคนอื่น
    """
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 24 * 7)))
    match = {"reason": "staff_grant", "created_at": {"$gte": since}}

    async def _names(ids: list) -> dict:
        return {
            u["_id"]: (u.get("display_name") or u.get("email") or "?")
            async for u in Col.users().find(
                {"_id": {"$in": ids}}, {"display_name": 1, "email": 1}
            )
        }

    # ── ยอดรวม ──
    totals = await Col.coin_transactions().aggregate([
        {"$match": match},
        {"$group": {"_id": None, "coins": {"$sum": "$amount"},
                    "grants": {"$sum": 1},
                    "receivers": {"$addToSet": "$user_id"}}},
    ]).to_list(1)
    t = totals[0] if totals else {}
    summary = {
        "coins": t.get("coins", 0),
        "grants": t.get("grants", 0),
        "receivers": len(t.get("receivers", [])),
    }

    # ── staff คนไหนจ่ายไปเท่าไหร่ ──
    by_staff = await Col.coin_transactions().aggregate([
        {"$match": match},
        {"$group": {"_id": "$actor_id", "coins": {"$sum": "$amount"},
                    "grants": {"$sum": 1}, "people": {"$addToSet": "$user_id"}}},
        {"$sort": {"coins": -1}}, {"$limit": top},
    ]).to_list(top)

    # ── ใครรับไปเยอะสุด ──
    by_user = await Col.coin_transactions().aggregate([
        {"$match": match},
        {"$group": {"_id": "$user_id", "coins": {"$sum": "$amount"},
                    "grants": {"$sum": 1}, "from_staff": {"$addToSet": "$actor_id"}}},
        {"$sort": {"coins": -1}}, {"$limit": top},
    ]).to_list(top)

    # ── ★ คู่ staff→ผู้รับ ที่จ่ายกันเยอะสุด — สัญญาณ "จ่ายให้พวกพ้อง" ──
    #   คนปกติรับจาก staff คนหนึ่งไม่กี่ครั้ง ถ้าคู่ไหนโดดขึ้นมาชัด ต้องไปดู
    pairs = await Col.coin_transactions().aggregate([
        {"$match": match},
        {"$group": {"_id": {"s": "$actor_id", "u": "$user_id"},
                    "coins": {"$sum": "$amount"}, "grants": {"$sum": 1}}},
        {"$sort": {"coins": -1}}, {"$limit": top},
    ]).to_list(top)

    ids = list({
        *[r["_id"] for r in by_staff if r["_id"]],
        *[r["_id"] for r in by_user if r["_id"]],
        *[p["_id"]["s"] for p in pairs if p["_id"].get("s")],
        *[p["_id"]["u"] for p in pairs if p["_id"].get("u")],
    })
    names = await _names(ids)

    return {
        "hours": hours,
        "summary": summary,
        "by_staff": [
            {"id": str(r["_id"]), "name": names.get(r["_id"], "?"),
             "coins": r["coins"], "grants": r["grants"], "people": len(r["people"])}
            for r in by_staff if r["_id"]
        ],
        "by_user": [
            {"id": str(r["_id"]), "name": names.get(r["_id"], "?"),
             "coins": r["coins"], "grants": r["grants"],
             "from_staff": len(r["from_staff"])}
            for r in by_user if r["_id"]
        ],
        "pairs": [
            {"staff": names.get(p["_id"].get("s"), "?"),
             "user": names.get(p["_id"].get("u"), "?"),
             "user_id": str(p["_id"].get("u")),
             "coins": p["coins"], "grants": p["grants"]}
            for p in pairs if p["_id"].get("s")
        ],
        "limits": {
            "per_scan": settings.STAFF_GRANT_MAX_PER_SCAN,
            "pair_daily": settings.STAFF_GRANT_PER_USER_DAILY,
            "receive_daily": settings.USER_GRANT_RECEIVE_DAILY,
            "staff_daily": settings.STAFF_GRANT_DAILY_BUDGET,
        },
    }


@router.post("/grants/reset-budget/{staff_id}")
async def reset_grant_budget(staff_id: str, admin: AdminDep, request: Request):
    """ล้างโควตารายวันของ staff — บูธที่คนต่อคิวจริงจนชนเพดาน

    ★ ไม่ล้างโควตา "ต่อผู้รับ" กับ "ผู้รับต่อวัน" — สองอันนั้นคือด่านกันพวกพ้อง
      ถ้าล้างได้ด้วยก็เท่ากับไม่มีด่าน
    """
    oid = ObjectId(staff_id)
    if not await Col.users().find_one({"_id": oid}, {"_id": 1}):
        raise not_found("ผู้ใช้")
    before = await grant_limits.reset_staff_budget(oid)
    await audit(request, admin, "grants.reset_budget", "user", staff_id,
                {"used_today": before}, {"used_today": 0})
    return {"ok": True, "cleared": before}


@router.get("/ig/queue")
async def ig_queue(admin: AdminDep, status: str = "pending", limit: int = 20):
    """คิวตรวจโพสต์ IG

    ★ ต้องส่ง image_data / caption / instagram_handle ของ "ใบที่ส่งมา" ออกไปด้วย
      ของเดิมไม่ส่งเลย → admin เห็นการ์ดเปล่า และชื่อ IG ที่โชว์คือ handle
      ในโปรไฟล์ผู้ใช้ ซึ่งเหมือนกันทุกใบที่คนเดียวกันส่ง = ดูเหมือน "คิวเดิมๆ"
      คนตรวจต้องเห็น "รูปกับคำที่จะขึ้นจอ" ตรงกับที่จะแสดงจริง ไม่งั้นอนุมัติมั่ว
    ★ limit ลดเหลือ 20 (เดิม 50) เพราะคิวนี้ยังต้องแนบ base64 มาจริงๆ
      (รูปที่ยังไม่อนุมัติเปิด public ไม่ได้) — หน้าเว็บ refetch ทุก 15 วิ
    """
    rows = await Col.ig_submissions().find({"status": status}).sort("submitted_at", 1).to_list(
        min(limit, 50)
    )
    user_ids = [r["user_id"] for r in rows]
    users = {
        u["_id"]: u
        async for u in Col.users().find(
            {"_id": {"$in": user_ids}},
            {"display_name": 1, "instagram_handle": 1, "avatar_url": 1},
        )
    }

    def _img(raw: str | None) -> str | None:
        """คืนเป็น data URL พร้อมใช้ — frontend เอาไปใส่ src ตรงๆ ได้เลย
        (ของเดิม frontend เดา prefix เอง แล้วเดาผิดถ้า DB เก็บ data: มาแล้ว)
        """
        if not raw:
            return None
        return raw if raw.startswith(("data:", "http")) else f"data:image/jpeg;base64,{raw}"

    return {
        "items": [
            {
                "id": str(r["_id"]), "shortcode": r["shortcode"], "post_url": r.get("post_url", ""),
                "status": r["status"], "submitted_at": r["submitted_at"],
                "auto_flags": r.get("auto_flags", []),
                # ★ ข้อมูลของใบนี้จริงๆ — คือสิ่งที่จะขึ้นจอถ้ากดอนุมัติ
                "image_data": _img(r.get("image_data")),
                "caption": r.get("caption", ""),
                "instagram_handle": r.get("instagram_handle"),
                "user": {
                    "id": str(r["user_id"]),
                    "display_name": users.get(r["user_id"], {}).get("display_name"),
                    "instagram_handle": users.get(r["user_id"], {}).get("instagram_handle"),
                },
            }
            for r in rows
        ],
        "total_pending": await Col.ig_submissions().count_documents({"status": "pending"}),
    }


@router.post("/ig/{submission_id}/approve")
async def approve_ig(submission_id: str, admin: AdminDep, request: Request):
    """อนุมัติให้ขึ้นจอ — ★ ไม่จ่ายเหรียญ

    ผู้ใช้ "จ่าย" IG_WALL_COST เพื่อซื้อที่บนจอ การอนุมัติคือการส่งมอบของที่ซื้อ
    ไม่ใช่รางวัล ของเดิมจ่าย IG_APPROVED_COINS (50) คืนให้ตอนอนุมัติ
    = ส่งรูปหนึ่งใบได้กำไร 30 เหรียญ ยิ่งส่งยิ่งรวย เหรียญเฟ้อทั้งงาน
    """
    sub = await Col.ig_submissions().find_one({"_id": ObjectId(submission_id)})
    if not sub:
        raise not_found("คำขอ")
    if sub["status"] != "pending":
        raise conflict("ALREADY_REVIEWED", f"คำขอนี้ถูกตรวจแล้ว (สถานะ: {sub['status']})")

    await Col.ig_submissions().update_one(
        {"_id": sub["_id"]},
        {"$set": {"status": "approved", "coins_awarded": 0,
                  "reviewed_by": admin.oid, "reviewed_at": datetime.now(timezone.utc)}},
    )
    await get_redis().zincrby(K.LB_IG, 1, str(sub["user_id"]))
    await audit(request, admin, "ig.approve", "ig_submission", submission_id,
                {"status": "pending"}, {"status": "approved", "coins": 0})
    return {"ok": True, "coins_awarded": 0}


@router.post("/ig/wall/clear")
async def clear_ig_wall(admin: AdminDep, request: Request):
    """ล้างคิว IG wall — ทำเครื่องหมายว่าทุกใบที่ค้างอยู่ "ฉายจบแล้ว"

    ใช้ตอนขึ้นวันใหม่ หรือตอนล้างข้อมูลทดสอบออกก่อนเปิดงานจริง
    ★ ไม่ลบโพสต์และไม่คืนเหรียญ — แค่เอาออกจากคิวจอ
      ประวัติยังอยู่ครบ (ทั้งใน submissions และ ledger) ย้อนดูได้ว่าใครส่งอะไร
      ถ้าจะให้ขึ้นใหม่ต้องแก้ใน DB (unset wall_shown_at) — ตั้งใจให้ทำยาก
      เพราะการ "ล้างจอ" ควรเป็นการตัดสินใจที่ทำแล้วจบ ไม่ใช่ปุ่มที่กดเล่นได้
    """
    res = await Col.ig_submissions().update_many(
        {"status": "approved", "wall_shown_at": {"$exists": False}},
        {"$set": {"wall_shown_at": datetime.now(timezone.utc)}},
    )
    await audit(request, admin, "ig.wall_clear", "ig_submission", "*",
                None, {"cleared": res.modified_count})
    return {"ok": True, "cleared": res.modified_count}


@router.post("/ig/{submission_id}/reject")
async def reject_ig(submission_id: str, admin: AdminDep, request: Request, reason: str = ""):
    """ปฏิเสธ + คืนเหรียญค่าส่ง

    ★ ของเดิมไม่คืนเหรียญ — ผู้ใช้จ่าย 20 เหรียญเพื่อ "ขึ้นจอ" แล้วไม่ได้ขึ้น
      เหรียญก็หายไปเฉยๆ หน้างานจะกลายเป็นคิวเถียงกับ staff
      คืนเงินผูก idempotency กับ shortcode → กดปฏิเสธซ้ำไม่คืนซ้ำ
    """
    sub = await Col.ig_submissions().find_one_and_update(
        {"_id": ObjectId(submission_id), "status": "pending"},
        {"$set": {"status": "rejected", "reject_reason": reason,
                  "reviewed_by": admin.oid, "reviewed_at": datetime.now(timezone.utc)}},
    )
    if not sub:
        raise conflict("ALREADY_REVIEWED", "คำขอนี้ถูกตรวจแล้ว")

    refund = await coins.award(
        user_id=sub["user_id"], amount=IG_WALL_COST, reason="ig_wall_refund",
        idempotency_key=f"ig:{sub['shortcode']}:refund",
        ref={"type": "ig_submission", "id": submission_id},
        actor_id=admin.oid, note=f"คืนเหรียญ ปฏิเสธโพสต์ ({reason[:80]})" if reason else "คืนเหรียญ ปฏิเสธโพสต์",
    )
    await audit(request, admin, "ig.reject", "ig_submission", submission_id,
                None, {"reason": reason, "refunded": IG_WALL_COST})
    return {"ok": True, "coins_refunded": IG_WALL_COST, "new_balance": refund.balance}


@router.post("/vote-rounds/{round_key}/{action}")
async def control_round(round_key: str, action: str, admin: AdminDep, request: Request):
    """เปิด / ปิด / ประกาศผลรอบโหวต"""
    mapping = {"open": "open", "close": "closed", "publish": "published"}
    if action not in mapping:
        raise conflict("INVALID_ACTION", "action ต้องเป็น open, close หรือ publish")

    updates: dict = {"status": mapping[action]}
    if action == "publish":
        updates["results_public"] = True

    # ตอนปิด: freeze tally จาก Redis ลง Mongo เป็นผลทางการ
    if action == "close":
        tally = await get_redis().hgetall(K.VOTE_TALLY.format(round=round_key))
        updates["final_tally"] = {k: int(v) for k, v in tally.items()}

    doc = await Col.vote_rounds().find_one_and_update(
        {"round_key": round_key}, {"$set": updates}, return_document=True
    )
    if not doc:
        raise not_found("รอบโหวต")

    await get_redis().delete(f"round:{round_key}")   # ล้าง cache ให้มีผลทันที
    await audit(request, admin, f"vote_round.{action}", "vote_round", round_key,
                None, {"status": mapping[action]})
    return {"ok": True, "status": mapping[action], "final_tally": updates.get("final_tally")}


# ── POST /admin/wheel/{key}/trigger ถูกถอดออกแล้ว ──────────────────────
# วงล้อเล่นในมือถือคนเล่นอย่างเดียว ไม่มีจอใหญ่หน้าเวที
# endpoint นี้เคยทำแค่ publish wheel.arm/wheel.spin ให้จอหมุนพร้อมกัน
# ไม่ได้แจกรางวัลหรือหักเหรียญใคร — เส้นทางจริงคือ POST /v1/wheel/{key}/spin


@router.patch("/config")
async def patch_config(body: ConfigPatchIn, admin: AdminDep, request: Request):
    """⚡ ปุ่มฉุกเฉิน — มีผลใน 5 วินาที ไม่ต้อง deploy ไม่ต้อง restart"""
    before = await Col.system_config().find_one({"_id": "global"}) or {}
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    updates["updated_by"] = admin.oid
    updates["updated_at"] = datetime.now(timezone.utc)

    await Col.system_config().update_one({"_id": "global"}, {"$set": updates}, upsert=True)
    await get_redis().delete(K.SYS_CONFIG)   # ล้าง cache ทันที
    await audit(request, admin, "config.patch", "system_config", "global", before, updates)
    return {"ok": True, "applied": updates}


@router.get("/audit-logs")
async def audit_logs(
    admin: AdminDep,
    limit: int = 50,
    action: str | None = None,
    actor_id: str | None = None,
    cursor: str | None = None,
):
    """ประวัติทุก action ของ admin

    ★ ของเดิมพังมาตลอด: คืน dict ดิบจาก Mongo ที่มี `actor_id` เป็น ObjectId
      แต่ app ตั้ง default_response_class=ORJSONResponse ซึ่ง serialize ObjectId ไม่ได้
      → endpoint นี้ตอบ 500 ทุกครั้ง ไม่เคยใช้งานได้เลย
      ตอนนี้แปลงเป็น str ทุกฟิลด์ + join ชื่อ admin มาให้อ่านรู้เรื่อง
    """
    q: dict = {}
    if action:
        # prefix match — พิมพ์ "quest" เจอทั้ง quest.create / quest.update / quest.delete
        q["action"] = {"$regex": f"^{re.escape(action)}"}
    if actor_id and ObjectId.is_valid(actor_id):
        q["actor_id"] = ObjectId(actor_id)
    if cursor and ObjectId.is_valid(cursor):
        q["_id"] = {"$lt": ObjectId(cursor)}

    n = min(limit, 200)
    rows = await Col.audit_logs().find(q).sort("_id", -1).to_list(n)

    actor_ids = [r["actor_id"] for r in rows if isinstance(r.get("actor_id"), ObjectId)]
    actors = {
        u["_id"]: u
        async for u in Col.users().find(
            {"_id": {"$in": actor_ids}}, {"display_name": 1, "email": 1}
        )
    } if actor_ids else {}

    def _plain(v):
        """ทำให้ orjson serialize ได้ — before/after เป็น dict อิสระ อาจมี ObjectId ซ่อนอยู่"""
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, dict):
            return {k: _plain(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_plain(x) for x in v]
        return v

    return {
        "items": [
            {
                "id": str(r["_id"]),
                "action": r.get("action", ""),
                "actor": {
                    "id": str(r.get("actor_id", "")),
                    "display_name": actors.get(r.get("actor_id"), {}).get("display_name"),
                    "email": actors.get(r.get("actor_id"), {}).get("email"),
                },
                "target": _plain(r.get("target") or {}),
                "before": _plain(r.get("before")),
                "after": _plain(r.get("after")),
                "user_agent": r.get("user_agent", ""),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
        "next_cursor": str(rows[-1]["_id"]) if len(rows) == n else None,
    }


@router.get("/audit-logs/actions")
async def audit_log_actions(admin: AdminDep):
    """รายการ action ที่มีจริงในระบบ — ให้หน้า UI ทำ dropdown กรองได้โดยไม่ต้อง hardcode"""
    return {"actions": sorted(await Col.audit_logs().distinct("action"))}


@router.get("/attendees")
async def list_attendees(
    admin: AdminDep,
    q: str = "",
    event_day: int | None = None,
    status: str | None = None,       # "checked" | "unchecked" | None
    limit: int = 50, cursor: str | None = None,
):
    """รายชื่อผู้สมัคร + สถานะเช็คอินรายวัน — สำหรับหน้า admin เช็คชื่อ

    ตรรกะอยู่ใน services/attendance.py เพราะ staff ใช้ตัวเดียวกัน (GET /staff/attendees)
    """
    return await query_attendees(q, event_day, status, limit, cursor)


@router.post("/checkin/manual", response_model=CheckinOut)
async def manual_checkin(body: ManualCheckinIn, admin: AdminDep, request: Request):
    """admin เช็คชื่อจากรายชื่อ (ไม่ใช้ QR) — กรณีบัตรพัง/หาย"""
    ticket = await Col.tickets().find_one({"user_id": ObjectId(body.user_id)})
    if not ticket:
        raise not_found("บัตร")
    if ticket["status"] == "revoked":
        return CheckinOut(result="revoked", event_day=body.event_day)

    out = await checkin_core(
        ticket=ticket,
        event_day=body.event_day,
        staff=admin,
        gate=body.gate,
        source="manual",
        device_id=None,
        scanned_at=None,
        idem_key=None,        # manual ไม่มี Idempotency-Key header → dedupe รายวันเป็นด่าน
        offline=False,
    )
    out.matched_by = "manual"
    await audit(request, admin, "checkin.manual", "user", body.user_id,
                {"event_day": body.event_day}, {"result": out.result})
    return out


@router.post("/checkin/undo")
async def undo_checkin(body: ManualCheckinIn, admin: AdminDep, request: Request):
    """ยกเลิกเช็คอินของวันนั้น — กรณี staff เลือกวันผิดแล้วสแกนไปแล้ว

    ★ ต้องล้างทั้ง 2 ด่าน ไม่งั้นเช็คอินใหม่ไม่ได้:
      - Mongo `checked_in_days` ($pull)
      - Redis `ci:{ticket_id}:d{day}` (ด่าน dedupe ตัวจริง)
    ★ ไม่คืนเหรียญ — coins.award ใช้ key `checkin:{code}:d{day}` อยู่แล้ว
      เช็คอินใหม่วันเดิมจึงไม่จ่ายซ้ำ ยอดจึงตรงเสมอ (บันทึกใน audit ครบ)
    """
    ticket = await Col.tickets().find_one({"user_id": ObjectId(body.user_id)})
    if not ticket:
        raise not_found("บัตร")
    if body.event_day not in (ticket.get("checked_in_days") or []):
        raise conflict("NOT_CHECKED_IN", f"ยังไม่ได้เช็คอินวันที่ {body.event_day} จึงยกเลิกไม่ได้")

    updated = await Col.tickets().find_one_and_update(
        {"_id": ticket["_id"]},
        {"$pull": {"checked_in_days": body.event_day}},
        return_document=True,
    )
    r = get_redis()
    await r.delete(K.CHECKIN_DEDUPE_DAY.format(ticket_id=str(ticket["_id"]), day=body.event_day))
    await r.srem(K.CHECKIN_DAY_SET.format(day=body.event_day), body.user_id)
    await r.hincrby(K.CHECKIN_STATS, f"day:{body.event_day}", -1)

    await Col.checkins().insert_one({
        "idempotency_key": f"undo:{ticket['ticket_code']}:d{body.event_day}:"
                           f"{int(datetime.now(timezone.utc).timestamp())}",
        "ticket_id": ticket["_id"], "ticket_code": ticket["ticket_code"],
        "event_day": body.event_day, "source": "admin_undo", "result": "undo",
        "gate": body.gate, "device_id": None, "staff_id": admin.oid,
        "scanned_at": datetime.now(timezone.utc), "received_at": datetime.now(timezone.utc),
        "offline_queued": False, "schema_version": 2,
    })
    await audit(request, admin, "checkin.undo", "user", body.user_id,
                {"checked_in_days": ticket.get("checked_in_days", [])},
                {"checked_in_days": updated.get("checked_in_days", [])})
    return {"ok": True, "checked_in_days": sorted(updated.get("checked_in_days", []))}


# ── Quests (บูธกิจกรรม) ────────────────────────────────────────────────
@router.get("/quests", response_model=list[QuestPublic])
async def admin_list_quests(admin: AdminDep):
    """ทุกกิจกรรม รวมที่ปิดอยู่ + จำนวนคนที่รับไปแล้ว"""
    rows = await Col.quests().find({}).sort("sort_order", 1).to_list(200)
    counts = {
        r["_id"]: r["n"]
        async for r in Col.quest_claims().aggregate(
            [{"$group": {"_id": "$quest_key", "n": {"$sum": 1}}}]
        )
    }
    return [
        QuestPublic(
            quest_key=q["quest_key"], title=q["title"],
            description=q.get("description", ""), coins=q.get("coins", 0),
            status=q["status"], max_per_user=q.get("max_per_user", 1),
            sort_order=q.get("sort_order", 0),
            claimed_count=counts.get(q["quest_key"], 0),
        )
        for q in rows
    ]


@router.post("/quests", response_model=QuestPublic, status_code=201)
async def create_quest(body: QuestIn, admin: AdminDep, request: Request):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    doc["schema_version"] = 1
    try:
        await Col.quests().insert_one(doc)
    except DuplicateKeyError:
        raise conflict("QUEST_EXISTS", f"มีกิจกรรมรหัส {body.quest_key} อยู่แล้ว")
    await audit(request, admin, "quest.create", "quest", body.quest_key, None, body.model_dump())
    return QuestPublic(**body.model_dump())


@router.patch("/quests/{quest_key}", response_model=QuestPublic)
async def update_quest(quest_key: str, body: QuestPatch, admin: AdminDep, request: Request):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise conflict("NOTHING_TO_UPDATE", "ไม่มีข้อมูลที่จะแก้")

    before = await Col.quests().find_one({"quest_key": quest_key})
    if not before:
        raise not_found("กิจกรรม")

    doc = await Col.quests().find_one_and_update(
        {"quest_key": quest_key}, {"$set": updates}, return_document=True
    )
    await audit(request, admin, "quest.update", "quest", quest_key,
                {k: before.get(k) for k in updates}, updates)
    claimed = await Col.quest_claims().count_documents({"quest_key": quest_key})
    return QuestPublic(
        quest_key=doc["quest_key"], title=doc["title"],
        description=doc.get("description", ""), coins=doc.get("coins", 0),
        status=doc["status"], max_per_user=doc.get("max_per_user", 1),
        sort_order=doc.get("sort_order", 0), claimed_count=claimed,
    )


@router.delete("/quests/{quest_key}")
async def delete_quest(quest_key: str, admin: AdminDep, request: Request):
    """ลบกิจกรรม

    ★ ถ้ามีคนรับเหรียญไปแล้ว จะ "ปิด" แทนการลบ — ลบทิ้งจะทำให้ ledger
      มีรายการ reason=quest ที่อ้างถึงกิจกรรมที่ไม่มีอยู่ ตรวจย้อนหลังไม่ได้
    """
    claimed = await Col.quest_claims().count_documents({"quest_key": quest_key})
    if claimed:
        doc = await Col.quests().find_one_and_update(
            {"quest_key": quest_key}, {"$set": {"status": "closed"}}, return_document=True
        )
        if not doc:
            raise not_found("กิจกรรม")
        await audit(request, admin, "quest.close_instead_of_delete", "quest", quest_key,
                    None, {"claimed": claimed})
        return {"ok": True, "deleted": False, "closed": True, "claimed_count": claimed,
                "message": f"มีคนรับไปแล้ว {claimed} ครั้ง — ปิดกิจกรรมแทนการลบ"}

    res = await Col.quests().delete_one({"quest_key": quest_key})
    if res.deleted_count == 0:
        raise not_found("กิจกรรม")
    await audit(request, admin, "quest.delete", "quest", quest_key, None, None)
    return {"ok": True, "deleted": True}


@router.post("/reconcile/points")
async def reconcile(admin: AdminDep, request: Request, fix: bool = True):
    """ซ่อม balance ให้ตรงกับ ledger — รันเมื่อเจอ alert coins_drift"""
    result = await coins.reconcile_all(fix=fix)
    await audit(request, admin, "coins.reconcile", "system", "global", None, result)
    return result


@router.post("/rebuild/leaderboard")
async def rebuild_lb(admin: AdminDep, request: Request):
    """สร้าง Redis leaderboard ใหม่จาก Mongo — ใช้หลัง Redis หายข้อมูล"""
    count = await coins.rebuild_leaderboard()
    await audit(request, admin, "leaderboard.rebuild", "system", "global", None, {"users": count})
    return {"ok": True, "users": count}
