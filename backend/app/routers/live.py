"""Live/public endpoints — อ่านอย่างเดียว, cache หนัก

เส้นทางนี้ต้องรับ 2,000 มือถือ poll ทุก 3 วิ = ~667 rps
แต่ Nginx micro-cache 1 วิ ทำให้ถึง Python จริงแค่ ~1 rps
"""
import json
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Request, Response

from app.core import ratelimit
from app.core.config import settings
from app.core.db import Col
from app.core.errors import not_found, unauthorized
from app.core.redis_client import K, get_redis

router = APIRouter(prefix="/live", tags=["live"])

# ★ header นี้คือสิ่งที่ทำให้ Nginx + Cloudflare cache ให้
CACHE_1S = "public, max-age=1, s-maxage=1, stale-while-revalidate=10"
CACHE_5S = "public, max-age=5, s-maxage=5, stale-while-revalidate=30"


@router.get("/snapshot")
async def snapshot(request: Request, response: Response):
    """สแนปช็อตสถานะทั้งงาน — สร้างโดย broadcaster ทุก 1 วิ

    ★ endpoint นี้ไม่คำนวณอะไรเลย แค่ GET จาก Redis แล้วคืนดิบๆ
      นี่คือเหตุผลที่รับ 667 rps ได้สบาย
    """
    await ratelimit.check_public("live", request)

    raw = await get_redis().get(K.SNAPSHOT)
    if not raw:
        # broadcaster ยังไม่ทำงาน หรือเพิ่ง restart
        response.headers["Cache-Control"] = "no-store"
        return {
            "server_time": datetime.now(timezone.utc).isoformat(),
            "seq": 0,
            "degraded": True,
            "message": "กำลังเตรียมข้อมูล",
        }

    data = json.loads(raw)

    # ETag → client ที่ข้อมูลไม่เปลี่ยนจะได้ 304 (ประหยัด bandwidth ทั้งสองฝั่ง)
    etag = f'W/"{data.get("seq", 0)}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE_1S})

    response.headers["Cache-Control"] = CACHE_1S
    response.headers["ETag"] = etag
    return data


# ── GET /live/leaderboard ถูกถอดออกแล้ว ────────────────────────────────
# ไม่มีหน้าอันดับ coin ในระบบแล้ว (ทั้งหน้าผู้ใช้และจอใหญ่)
# zset LB_COINS ยังเขียนอยู่ตามปกติ เพราะใช้คำนวณ `rank` ส่วนตัวใน /me
# ถ้าจะเอาหน้าอันดับกลับมา แค่เพิ่ม endpoint นี้กลับ — ข้อมูลไม่ได้หายไปไหน


@router.get("/checkin-stats")
async def checkin_stats(request: Request, response: Response):
    await ratelimit.check_public("live", request)
    response.headers["Cache-Control"] = "public, max-age=3, s-maxage=3"

    r = get_redis()
    stats = await r.hgetall(K.CHECKIN_STATS)
    now = datetime.now(timezone.utc).timestamp()
    rate = await r.zcount(K.CHECKIN_TS, now - 60, now)
    recent_raw = await r.lrange(K.CHECKIN_RECENT, 0, 19)

    return {
        "today": int(stats.get("today", 0)),
        "rate_per_min": int(rate),
        "gates": {
            k.replace("gate:", ""): int(v) for k, v in stats.items() if k.startswith("gate:")
        },
        "recent": [json.loads(x) for x in recent_raw],
        "as_of": datetime.now(timezone.utc),
    }


@router.get("/ig-wall")
async def ig_wall(request: Request, response: Response, limit: int = 20):
    """จอ IG wall — ดึงโพสต์ที่อนุมัติแล้วพร้อมรูป สำหรับจอใหญ่หน้างาน

    public endpoint — จอ display ดึงทุก 10 วิ
    ★ ส่ง "ลิงก์รูป" ไม่ใช่ base64
      ของเดิมยัด base64 ทุกใบมาในก้อน JSON → 30 ใบ × ~1MB = โหลดใหม่ทั้งกอง
      ทุกครั้งที่ poll ตลอดงาน (จอค้าง เน็ตหน้างานตาย)
      แยกเป็น /ig/image/{id} ซึ่ง cache 1 วัน → หลังรอบแรกแทบไม่กิน bandwidth
    ★ เรียง "เก่า → ใหม่" (ใบล่าสุดอยู่ท้ายสุด)
      จอเดินหน้าจาก index 0 ไปเรื่อยๆ และตอนมีใบใหม่เข้ามาจะกระโดดไป items[length-1]
      ถ้าเรียงใหม่→เก่า (ของเดิม) การกระโดดนั้นจะไปโผล่ "ใบเก่าสุด" แทน
      → อาการคือ อนุมัติรูปใหม่แล้วจอยังวนโชว์รูปคิวเดิม

    ★ ใบที่ขึ้นจอครบเวลาแล้ว (มี wall_shown_at) จะไม่ถูกส่งมาอีก
      กติกาคือ "ขึ้นจอคนละครั้ง" ไม่ใช่วนซ้ำ — คนจ่าย 20 เหรียญเพื่อได้ขึ้นจอ
      หนึ่งรอบ ไม่ใช่เพื่อยึดจอทั้งงาน และการวนซ้ำทำให้ใบใหม่ต้องรอนานขึ้นเรื่อยๆ
      จอเป็นคนบอกว่าฉายจบแล้ว (POST .../shown) ไม่ใช่ backend เดาเอง —
      ถ้า backend นับเวลาเองแล้ววันไหนไม่มีใครเปิดจอ คิวจะไหลทิ้งโดยไม่มีใครเห็น
    """
    await ratelimit.check_public("live", request)
    response.headers["Cache-Control"] = "public, max-age=5, s-maxage=5"

    # ★ ไม่ดึง image_data ออกมาเลย (projection ตัดทิ้ง) — คิวรี่เบาลงมาก
    rows = await Col.ig_submissions().find(
        {"status": "approved", "image_data": {"$exists": True},
         "wall_shown_at": {"$exists": False}},
        {"instagram_handle": 1, "caption": 1, "user_id": 1, "reviewed_at": 1, "_id": 1},
    ).sort("reviewed_at", -1).to_list(min(limit, 50))
    rows.reverse()

    # ดึงชื่อผู้ใช้แต่ละคน
    user_ids = [r["user_id"] for r in rows if r.get("user_id")]
    users = {
        u["_id"]: u
        async for u in Col.users().find(
            {"_id": {"$in": user_ids}},
            {"display_name": 1},
        )
    } if user_ids else {}

    items = []
    for r in rows:
        items.append({
            "id": str(r["_id"]),
            "image_url": f"{settings.API_BASE_URL}/v1/ig/image/{r['_id']}",
            "instagram_handle": r.get("instagram_handle"),
            "caption": r.get("caption"),
            "display_name": users.get(r.get("user_id"), {}).get("display_name"),
            "shown_at": r.get("reviewed_at"),
        })

    return {"items": items, "as_of": datetime.now(timezone.utc)}


@router.post("/ig-wall/{submission_id}/shown")
async def mark_ig_wall_shown(submission_id: str, token: str = ""):
    """จอแจ้งว่า "ใบนี้ฉายครบเวลาแล้ว" → ตัดออกจากคิว ไม่ขึ้นซ้ำอีก

    ★ ทำไมให้จอเป็นคนบอก ไม่ให้ backend จับเวลาเอง
      ถ้า backend นับเอง คิวจะไหลทิ้งแม้ไม่มีใครเปิดจอ — คนจ่าย 20 เหรียญ
      ตอนตีสองแล้วสิทธิ์หมดไปโดยไม่มีใครได้เห็นเลย
      ทางนี้ถ้าจอดับ ใบนั้นก็แค่ยังค้างคิวไว้ รอบหน้าเปิดจอมาก็ได้ฉายต่อ
      (พังไปทางที่ปลอดภัยกว่า)

    ★ ต้องมี DISPLAY_TOKEN — endpoint นี้ "เผา" สิทธิ์ที่คนจ่ายเงินซื้อมา
      ถ้าเปิดโล่ง ใครก็ยิงรัวให้โพสต์คนอื่นหายจากคิวได้หมด
    """
    if not settings.DISPLAY_TOKEN or token != settings.DISPLAY_TOKEN:
        raise unauthorized("จอไม่ได้รับอนุญาต — เปิดหน้าจอด้วย ?token=DISPLAY_TOKEN")

    try:
        oid = ObjectId(submission_id)
    except Exception:
        raise not_found("โพสต์") from None

    # ★ เขียนเฉพาะใบที่ยังไม่เคยถูกทำเครื่องหมาย — ยิงซ้ำไม่เปลี่ยนเวลาที่บันทึกไว้
    #   (จอ reconnect แล้วส่งซ้ำได้ ไม่ควรทำให้ประวัติเพี้ยน)
    res = await Col.ig_submissions().update_one(
        {"_id": oid, "wall_shown_at": {"$exists": False}},
        {"$set": {"wall_shown_at": datetime.now(timezone.utc)}},
    )
    return {"ok": True, "marked": res.modified_count == 1}
