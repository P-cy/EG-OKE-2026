"""ดาวน์โหลดข้อมูลเป็น CSV — เปิดใน Excel / Google Sheets ได้ตรงๆ

ใช้ตอนงานจบแล้วอยากไล่ย้อนหลังว่าใครเข้างานตอนไหน ใครได้เหรียญจากอะไร
หรือตอนมีคนทักว่า "ผมเช็คอินแล้วนะ" แล้วต้องพิสูจน์

★ กับดัก 3 อย่างที่ทำให้ไฟล์เปิดใน Excel แล้วใช้ไม่ได้ (แก้ไว้หมดแล้ว):

  1. BOM — Excel บน Windows ไม่เดา UTF-8 ให้ ถ้าไม่มี BOM นำหน้า
     ภาษาไทยจะกลายเป็นขยะทั้งไฟล์ (à¸ªà¸§à¸±à¸ªà¸”à¸µ) และไม่มีทางกู้จากในโปรแกรม
     ต้อง import wizard ใหม่ทั้งไฟล์ ซึ่งไม่มีใครรู้วิธี

  2. รูปแบบเวลา — ต้องเป็น "YYYY-MM-DD HH:MM:SS" Excel ถึงจะรู้ว่าเป็นวันเวลา
     แล้ว sort/filter ได้ ถ้าส่ง ISO 8601 ที่มี T กับ Z ไป มันอ่านเป็นข้อความ
     เรียงลำดับผิด (เรียงตามตัวอักษร)

  3. เวลาไทย — ข้อมูลใน Mongo เป็น UTC ถ้าไม่แปลง ทุกแถวจะเพี้ยนไป 7 ชั่วโมง
     คนเช็คอิน 9 โมงเช้าจะกลายเป็นตี 2

★ ใช้ offset คงที่ +07:00 ไม่ใช่ ZoneInfo("Asia/Bangkok")
  เพราะ ZoneInfo ต้องมี tzdata ติดมากับ image ถ้าไม่มีจะพังตอน runtime เท่านั้น
  (import ผ่าน เทสต์ผ่าน แต่กดดาวน์โหลดจริงแล้ว 500) ไทยไม่มี DST อยู่แล้ว
"""
import csv
import io
from datetime import datetime, timezone
from typing import Annotated, AsyncIterator

from bson import ObjectId
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.db import Col
from app.core.deps import CurrentUser, require_admin
from app.core.timeutil import TH

router = APIRouter(prefix="/admin/export", tags=["admin"])
AdminDep = Annotated[CurrentUser, Depends(require_admin)]

PAGE = 1000

# ผลการสแกนเป็นภาษาไทย — คนที่เปิดไฟล์ไม่ใช่โปรแกรมเมอร์
RESULT_TH = {
    "ok": "ผ่าน",
    "duplicate": "เข้าแล้ว (สแกนซ้ำ)",
    "not_found": "ไม่พบบัตร",
    "no_ticket": "ยังไม่มีบัตร",
    "invalid_sig": "รหัสไม่ถูกต้อง",
    "revoked": "บัตรถูกยกเลิก",
    "rotating_code_mismatch": "รหัสหมุนไม่ตรง",
    "wrong_day": "ผิดวัน",
    "expired": "หมดอายุ",
    "undo": "ถูกยกเลิกโดย admin",
    "error": "ผิดพลาด",
}

SOURCE_TH = {
    "qr": "สแกน QR",
    "ticket_code": "พิมพ์รหัสบัตร",
    "student_id": "พิมพ์รหัสนักศึกษา",
    "manual": "เช็คด้วยมือจากรายชื่อ",
    "admin_undo": "admin ยกเลิก",
}


def _th_time(dt) -> str:
    """UTC → เวลาไทย ในรูปแบบที่ Excel รู้จักว่าเป็นวันเวลา"""
    if not isinstance(dt, datetime):
        return ""
    # motor ตั้ง tz_aware=True ไว้แล้ว แต่ข้อมูลเก่าที่เขียนก่อนหน้านั้นอาจเป็น naive
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TH).strftime("%Y-%m-%d %H:%M:%S")


def _csv_row(values: list) -> str:
    buf = io.StringIO()
    # QUOTE_MINIMAL + \r\n = สิ่งที่ Excel คาดหวัง
    csv.writer(buf, lineterminator="\r\n").writerow(values)
    return buf.getvalue()


def _download(rows: AsyncIterator[str], filename: str) -> StreamingResponse:
    return StreamingResponse(
        rows,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # ไฟล์นี้เปลี่ยนตลอด ห้าม cache
            "Cache-Control": "no-store",
        },
    )


async def _user_lookup(user_ids: list[ObjectId]) -> dict[ObjectId, dict]:
    return {
        u["_id"]: u
        async for u in Col.users().find(
            {"_id": {"$in": user_ids}},
            {"email": 1, "display_name": 1, "full_name": 1, "student_id": 1,
             "faculty": 1, "department": 1, "instagram_handle": 1,
             "coins_balance": 1, "created_at": 1},
        )
    }


@router.get("/checkins.csv")
async def export_checkins(admin: AdminDep, event_day: int | None = None, result: str | None = None):
    """ทุกครั้งที่มีการสแกน — รวมครั้งที่ถูกปฏิเสธด้วย

    นี่คือหลักฐานว่าใครเข้างานตอนไหน กี่โมง ที่ประตูไหน ใครเป็นคนสแกน
    """
    query: dict = {}
    if event_day is not None:
        query["event_day"] = event_day
    if result:
        query["result"] = result

    async def rows() -> AsyncIterator[str]:
        yield "﻿"      # ★ BOM — ขาดอันนี้ภาษาไทยพังทั้งไฟล์
        yield _csv_row([
            "เวลา (ไทย)", "วันงาน", "ผลลัพธ์", "ชื่อเล่น", "ชื่อจริง", "อีเมล",
            "รหัสนักศึกษา", "คณะ", "สาขา", "รหัสบัตร", "ช่องทาง", "ประตู",
            "เครื่องที่สแกน", "ผู้สแกน", "ส่งจากคิวออฟไลน์",
        ])

        # เรียงเก่า→ใหม่ อ่านเป็นไทม์ไลน์ได้เลย
        cursor = Col.checkins().find(query).sort("scanned_at", 1)
        batch: list[dict] = []

        async def flush(batch: list[dict]) -> AsyncIterator[str]:
            if not batch:
                return
            # join ทีละก้อน — ไม่ยิง query ต่อแถว (15,000 แถว = 15,000 query)
            ticket_ids = [b["ticket_id"] for b in batch if b.get("ticket_id")]
            tickets = {
                t["_id"]: t
                async for t in Col.tickets().find(
                    {"_id": {"$in": ticket_ids}}, {"user_id": 1}
                )
            }
            uids = [t["user_id"] for t in tickets.values()]
            uids += [b["staff_id"] for b in batch if b.get("staff_id")]
            users = await _user_lookup(list(set(uids)))

            for c in batch:
                t = tickets.get(c.get("ticket_id")) or {}
                u = users.get(t.get("user_id")) or {}
                s = users.get(c.get("staff_id")) or {}
                yield _csv_row([
                    _th_time(c.get("scanned_at")),
                    c.get("event_day", ""),
                    RESULT_TH.get(c.get("result", ""), c.get("result", "")),
                    u.get("display_name", ""),
                    u.get("full_name", ""),
                    u.get("email", ""),
                    u.get("student_id", ""),
                    u.get("faculty", ""),
                    u.get("department", ""),
                    c.get("ticket_code", ""),
                    SOURCE_TH.get(c.get("source", ""), c.get("source", "")),
                    c.get("gate", ""),
                    c.get("device_id", "") or "",
                    s.get("display_name", "") or s.get("email", ""),
                    "ใช่" if c.get("offline_queued") else "",
                ])

        async for doc in cursor:
            batch.append(doc)
            if len(batch) >= PAGE:
                async for line in flush(batch):
                    yield line
                batch = []
        async for line in flush(batch):
            yield line

    stamp = datetime.now(TH).strftime("%Y%m%d-%H%M")
    return _download(rows(), f"egoke-checkins-{stamp}.csv")


@router.get("/attendees.csv")
async def export_attendees(admin: AdminDep):
    """รายชื่อทุกคน + สรุปว่าเข้าวันไหนบ้าง — หนึ่งคนหนึ่งแถว"""

    async def rows() -> AsyncIterator[str]:
        yield "﻿"
        yield _csv_row([
            "ชื่อเล่น", "ชื่อจริง", "อีเมล", "รหัสนักศึกษา", "คณะ", "สาขา",
            "Instagram", "รหัสบัตร", "สถานะบัตร",
            "วัน1", "วัน2", "วัน3", "จำนวนวันที่เข้า",
            "เช็คอินล่าสุด", "เหรียญคงเหลือ", "สมัครเมื่อ",
        ])

        batch: list[dict] = []

        async def flush(batch: list[dict]) -> AsyncIterator[str]:
            if not batch:
                return
            tickets = {
                t["user_id"]: t
                async for t in Col.tickets().find({"user_id": {"$in": [b["_id"] for b in batch]}})
            }
            for u in batch:
                t = tickets.get(u["_id"]) or {}
                days = t.get("checked_in_days", [])
                yield _csv_row([
                    u.get("display_name", ""),
                    u.get("full_name", ""),
                    u.get("email", ""),
                    u.get("student_id", ""),
                    u.get("faculty", ""),
                    u.get("department", ""),
                    u.get("instagram_handle", ""),
                    t.get("ticket_code", ""),
                    t.get("status", "ยังไม่มีบัตร"),
                    "เข้า" if 1 in days else "",
                    "เข้า" if 2 in days else "",
                    "เข้า" if 3 in days else "",
                    len(days),
                    _th_time(t.get("last_checked_in_at")),
                    u.get("coins_balance", 0),
                    _th_time(u.get("created_at")),
                ])

        async for doc in Col.users().find({}).sort("_id", 1):
            batch.append(doc)
            if len(batch) >= PAGE:
                async for line in flush(batch):
                    yield line
                batch = []
        async for line in flush(batch):
            yield line

    stamp = datetime.now(TH).strftime("%Y%m%d-%H%M")
    return _download(rows(), f"egoke-attendees-{stamp}.csv")


# ที่มาของเหรียญเป็นภาษาไทย — คนอ่านคือทีมงาน ไม่ใช่โปรแกรมเมอร์
REASON_TH = {
    "checkin": "เช็คอินเข้างาน",
    "staff_grant": "staff จ่ายที่บูธ",
    "quest": "กิจกรรม (ระบบเก่า)",
    "admin_adjust": "admin ปรับด้วยมือ",
    "wheel_spin": "หมุนวงล้อ (ค่าหมุน)",
    "wheel_prize": "รางวัลวงล้อ",
    "ig_wall": "ค่าขึ้นจอ IG",
    "ig_wall_refund": "คืนค่าขึ้นจอ IG",
}


@router.get("/coins.csv")
async def export_coins(admin: AdminDep, reason: str | None = None):
    """ทุกการเคลื่อนไหวของเหรียญ — เข้าและออก

    ★ นี่คือไฟล์ที่ใช้กระทบยอดกับบูธ: กรอง `staff จ่ายที่บูธ` ใน Excel
      แล้วรวมยอดตาม "ผู้จ่าย" หรือ "เครื่อง" ได้เลย
    ★ ยอดคงเหลือหลังรายการ มาจาก ledger ตอนนั้นจริงๆ ไม่ได้คำนวณย้อนหลัง
      ถ้าตัวเลขไม่ไล่ต่อกัน แปลว่ามีอะไรผิดปกติที่ต้องตามต่อ
    """
    query: dict = {}
    if reason:
        query["reason"] = reason

    async def rows() -> AsyncIterator[str]:
        yield "﻿"
        yield _csv_row([
            "เวลา (ไทย)", "ชื่อเล่น", "ชื่อจริง", "อีเมล", "รหัสนักศึกษา",
            "จำนวน", "ยอดคงเหลือหลังรายการ", "ที่มา", "ผู้ทำรายการ",
            "เครื่อง", "หมายเหตุ",
        ])

        batch: list[dict] = []

        async def flush(batch: list[dict]) -> AsyncIterator[str]:
            if not batch:
                return
            uids = [b["user_id"] for b in batch]
            uids += [b["actor_id"] for b in batch if b.get("actor_id")]
            users = await _user_lookup(list(set(uids)))
            for c in batch:
                u = users.get(c["user_id"]) or {}
                a = users.get(c.get("actor_id")) or {}
                yield _csv_row([
                    _th_time(c.get("created_at")),
                    u.get("display_name", ""),
                    u.get("full_name", ""),
                    u.get("email", ""),
                    u.get("student_id", ""),
                    c.get("amount", 0),
                    c.get("balance_after", ""),
                    REASON_TH.get(c.get("reason", ""), c.get("reason", "")),
                    a.get("display_name", "") or a.get("email", "") or "ระบบ",
                    (c.get("ref") or {}).get("device_id", "") or "",
                    c.get("note", "") or "",
                ])

        async for doc in Col.coin_transactions().find(query).sort("created_at", 1):
            batch.append(doc)
            if len(batch) >= PAGE:
                async for line in flush(batch):
                    yield line
                batch = []
        async for line in flush(batch):
            yield line

    stamp = datetime.now(TH).strftime("%Y%m%d-%H%M")
    return _download(rows(), f"egoke-coins-{stamp}.csv")
