"""ทดสอบระบบเช็คชื่อเข้างาน — ส่วนที่พลาดแล้วคนต่อคิวหน้าประตู

แบ่ง 2 ชั้น:
  · pure   — classify_code / ข้อความที่ staff เห็น (ไม่ต้องมี DB รันได้ทุกที่)
  · integ  — checkin_core บน Mongo+Redis จริง (skip อัตโนมัติถ้าต่อไม่ได้)
"""
import asyncio

import pytest

from app.models.schemas import CheckinIn, CheckinOut
from app.routers.checkin import REASON_MESSAGE, classify_code
from app.core.security import build_qr_payload

TICKET = "EGOKE26-1E4A5AEE"


# ── classify_code: ทางเข้า 3 ทางต้องแยกออกถูก ──────────────────────────
@pytest.mark.parametrize("raw,kind", [
    (build_qr_payload(TICKET),        "qr"),
    (TICKET,                          "ticket_code"),
    (TICKET.lower(),                  "ticket_code"),   # staff พิมพ์ตัวเล็ก
    (f"  {TICKET}  ",                 "ticket_code"),   # copy มามีช่องว่าง
    ("6913099",                       "student_id"),
    ("691309",                        "unknown"),       # 6 หลัก ไม่ใช่รหัส นศ.
    ("69130999",                      "unknown"),       # 8 หลัก
    ("EGOKE26-",                      "unknown"),       # รหัสไม่ครบ
    ("hello world",                   "unknown"),
    ("",                              "unknown"),
])
def test_classify_code(raw, kind):
    assert classify_code(raw)[0] == kind


def test_classify_normalizes_ticket_code_to_upper():
    """staff พิมพ์ตัวเล็ก ต้องค้นเจอ — ticket_code ใน DB เก็บเป็นตัวใหญ่"""
    assert classify_code("egoke26-1e4a5aee")[1] == "EGOKE26-1E4A5AEE"


def test_classify_does_not_mistake_qr_for_ticket_code():
    """QR payload มี ticket_code อยู่ข้างใน — ต้องไม่ถูกจับเป็น ticket_code"""
    kind, code = classify_code(build_qr_payload(TICKET))
    assert kind == "qr" and code.startswith("EGOKE2:")


# ── สัญญาระหว่าง schema กับ UI ─────────────────────────────────────────
def test_min_length_accepts_student_id():
    """★ บั๊กจริงที่เคยเกิด: min_length=20 ทำให้รหัสบัตร/รหัส นศ. โดน 422
       แล้ว frontend โชว์ "UNKNOWN" ให้ staff เห็นเต็มจอ
    """
    for code in (TICKET, "6913099"):
        body = CheckinIn(payload=code, event_day=1, device_id="d1")
        assert body.payload == code


@pytest.mark.parametrize("day", [0, 4, -1])
def test_event_day_out_of_range_rejected(day):
    with pytest.raises(Exception):
        CheckinIn(payload=TICKET, event_day=day, device_id="d1")


def test_every_failure_reason_has_thai_message():
    """staff ต้องอ่านออกทุกกรณี — ห้ามมี result ไหนที่โผล่มาแล้วไม่มีคำอธิบาย"""
    for reason in ("malformed", "invalid_sig", "wrong_version",
                   "not_found", "no_ticket", "revoked", "rotating_code_mismatch"):
        msg = REASON_MESSAGE[reason]
        assert msg and not msg.isascii(), f"{reason} ต้องมีข้อความภาษาไทย"


def test_checkin_out_results_cover_what_frontend_renders():
    """frontend มีตาราง RESULT_UI ต่อ result — ถ้า backend เพิ่ม result ใหม่
    โดยไม่เพิ่มใน frontend จะโชว์ค่าดิบให้ staff เห็น เทสต์นี้กันไม่ให้ลืม
    """
    backend_results = set(CheckinOut.model_fields["result"].annotation.__args__)
    frontend_renders = {
        "ok", "duplicate", "invalid_sig", "revoked", "no_ticket",
        "wrong_day", "expired", "rotating_code_mismatch", "not_found",
    }
    assert backend_results == frontend_renders, (
        "backend/frontend result ไม่ตรงกัน — อัปเดต RESULT_UI ใน "
        "frontend/src/app/scan/page.tsx ด้วย"
    )


# ── integration: dedupe รายวันบน Mongo+Redis จริง ─────────────────────
@pytest.mark.asyncio
async def test_checkin_dedupe_per_day(ticket_fixture, staff_user):
    """สแกนวันเดียวกันรัวๆ ต้องได้ ok ครั้งเดียว แต่ข้ามวันต้องได้ใหม่

    ★ ข้อสำคัญ: 10 request พร้อมกัน (คนสแกนรัว/เน็ตช้าแล้วกดซ้ำ)
      ถ้า dedupe พังจะจ่ายเหรียญซ้ำและตัวเลขผู้เข้างานเฟ้อ
    """
    from app.routers.checkin import checkin_core

    async def scan(day: int):
        return await checkin_core(
            ticket=ticket_fixture, event_day=day, staff=staff_user,
            gate="TEST", source="qr", device_id="d1",
            scanned_at=None, idem_key=None,
        )

    results = await asyncio.gather(*[scan(1) for _ in range(10)])
    oks = [r for r in results if r.result == "ok"]
    assert len(oks) == 1, f"ต้องผ่านครั้งเดียว ได้ {len(oks)}"
    assert all(r.result == "duplicate" for r in results if r not in oks)

    # ข้ามวัน = เช็คอินใหม่ได้
    day2 = await scan(2)
    assert day2.result == "ok"
    assert sorted(day2.ticket["checked_in_days"]) == [1, 2]


@pytest.mark.asyncio
async def test_checkin_coins_awarded_once_per_day(ticket_fixture, staff_user, db):
    """มา 2 วัน = ได้เหรียญ 2 ครั้ง, สแกนซ้ำวันเดิม = ไม่ได้เพิ่ม"""
    from app.core.config import settings
    from app.routers.checkin import checkin_core

    async def scan(day: int):
        return await checkin_core(
            ticket=ticket_fixture, event_day=day, staff=staff_user,
            gate="TEST", source="qr", device_id="d1",
            scanned_at=None, idem_key=None,
        )

    a = await scan(1)
    await scan(1)          # ซ้ำ
    b = await scan(2)

    assert a.coins_awarded == settings.CHECKIN_COINS
    assert b.coins_awarded == settings.CHECKIN_COINS

    user = await db["users"].find_one({"_id": ticket_fixture["user_id"]})
    assert user["coins_balance"] == settings.CHECKIN_COINS * 2
