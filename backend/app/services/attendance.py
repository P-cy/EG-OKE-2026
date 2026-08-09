"""รายชื่อผู้เข้างาน + เช็คชื่อด้วยมือ — ใช้ร่วมกันระหว่าง admin กับ staff

★ ทำไมต้องแยกออกมา:
  staff ที่ประตูต้องค้นรายชื่อและกดเช็คชื่อได้ (บัตรพัง/มือถือแบตหมด/QR สแกนไม่ติด)
  แต่ต้องไม่ได้สิทธิ์อย่างอื่นของ admin ติดมาด้วย — ยกเลิกเช็คอิน ปรับเหรียญ
  ตั้ง role แก้ config พวกนี้ต้องอยู่กับ admin เท่านั้น
  ถ้าปล่อยให้ตรรกะอยู่ใน routers/admin.py แล้วให้ staff เรียก endpoint เดิม
  = ต้องเปิดสิทธิ์ทั้ง router ให้ staff ซึ่งเปิดเกินที่ตั้งใจไปมาก
"""
import re

from bson import ObjectId

from app.core.db import Col
from app.models.schemas import AttendeeRow

MAX_PAGE = 200


async def query_attendees(
    q: str = "",
    event_day: int | None = None,
    status: str | None = None,      # "checked" | "unchecked" | None
    limit: int = 50,
    cursor: str | None = None,
) -> dict:
    """รายชื่อผู้สมัคร + สถานะเช็คอินรายวัน"""
    page = min(limit, MAX_PAGE)
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

    rows = await Col.users().find(query).sort("_id", 1).to_list(page)
    user_ids = [u["_id"] for u in rows]
    tickets = {
        t["user_id"]: t
        async for t in Col.tickets().find({"user_id": {"$in": user_ids}})
    }

    items: list[dict] = []
    for u in rows:
        t = tickets.get(u["_id"])
        days = (t or {}).get("checked_in_days", [])
        # กรองที่ต้อง join ticket ก่อนรู้ค่า — ทำใน Python (5000 คน 50/page ไม่มีปัญหา)
        if event_day is not None and event_day not in days:
            continue
        if status == "checked" and not days:
            continue
        if status == "unchecked" and days:
            continue
        items.append(AttendeeRow(
            id=str(u["_id"]), email=u["email"],
            display_name=u.get("display_name"), full_name=u.get("full_name"),
            student_id=u.get("student_id"),
            faculty=u.get("faculty"), department=u.get("department"),
            ticket_code=(t or {}).get("ticket_code"),
            ticket_status=(t or {}).get("status"),
            checked_in_days=days,
            last_checked_in_at=(t or {}).get("last_checked_in_at"),
            coins_balance=u.get("coins_balance", 0),
        ).model_dump(mode="json"))

    return {
        "items": items,
        # cursor นับจาก rows ดิบ (ก่อนกรอง) เพื่อให้ paginate ไม่มี skip
        "next_cursor": str(rows[-1]["_id"]) if len(rows) == page else None,
    }
