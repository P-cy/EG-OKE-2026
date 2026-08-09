"""CSV export — ต้องเปิดใน Excel แล้วอ่านออก

เทสต์นี้มีอยู่เพราะความผิดพลาดตรงนี้ตรวจไม่เจอจนกว่าจะมีคนเปิดไฟล์จริง
(endpoint ตอบ 200 ไฟล์โหลดได้ ทุกอย่างดูปกติ — แต่เปิดมาเป็นขยะ)
"""
from datetime import datetime, timezone

from app.routers.exports import RESULT_TH, SOURCE_TH, TH, _csv_row, _th_time


def test_bom_is_the_first_thing_written():
    """★ กับดักหลัก — Excel บน Windows ไม่เดา UTF-8 ให้

    ถ้าไม่มี BOM นำหน้า ภาษาไทยจะกลายเป็น à¸ªà¸§à¸±à¸ª ทั้งไฟล์
    และแก้จากในโปรแกรมไม่ได้ ต้อง import ใหม่ทั้งไฟล์ซึ่งไม่มีใครรู้วิธี
    """
    bom = "﻿"
    assert bom.encode("utf-8") == b"\xef\xbb\xbf"
    # ยืนยันว่าค่าที่โค้ดจริง yield ออกไปคือ BOM ตัวนี้ ไม่ใช่ช่องว่างที่มองไม่เห็น
    import inspect

    from app.routers import exports
    src = inspect.getsource(exports)
    endpoints = src.count("@router.get(")
    assert src.count('yield "﻿"') == endpoints, "ทุก endpoint ต้อง yield BOM เป็นบรรทัดแรก"


def test_time_is_thai_time_not_utc():
    """ข้อมูลใน Mongo เป็น UTC — ไม่แปลงแล้วทุกแถวเพี้ยน 7 ชั่วโมง"""
    utc_2am = datetime(2026, 8, 7, 2, 30, 0, tzinfo=timezone.utc)
    assert _th_time(utc_2am) == "2026-08-07 09:30:00", "ตี 2 UTC = 9 โมงเช้าที่ไทย"


def test_time_format_is_sortable_in_excel():
    """ต้องเป็น YYYY-MM-DD HH:MM:SS ไม่ใช่ ISO 8601 ที่มี T กับ Z

    ถ้าส่ง ISO ไป Excel อ่านเป็นข้อความ แล้วเรียงลำดับตามตัวอักษร
    """
    out = _th_time(datetime(2026, 8, 7, 2, 30, 0, tzinfo=timezone.utc))
    assert "T" not in out and "Z" not in out and "+" not in out
    assert len(out) == 19


def test_naive_datetime_is_treated_as_utc():
    """ข้อมูลที่เขียนก่อนตั้ง tz_aware=True เป็น naive — ต้องไม่พังและไม่เพี้ยน"""
    naive = datetime(2026, 8, 7, 2, 30, 0)
    assert _th_time(naive) == "2026-08-07 09:30:00"


def test_missing_time_becomes_empty_cell():
    """คนที่ยังไม่เคยเช็คอินมี last_checked_in_at = None — ต้องไม่ทำให้ทั้งไฟล์พัง"""
    assert _th_time(None) == ""
    assert _th_time("") == ""


def test_row_uses_crlf_like_excel_expects():
    assert _csv_row(["a", "b"]).endswith("\r\n")


def test_thai_text_with_comma_is_quoted():
    """ชื่อกิจกรรมมีจุลภาคได้ — ไม่ quote แล้วคอลัมน์เลื่อนทั้งแถว"""
    row = _csv_row(["บูธยิงปืน, ฐาน 2", "10"])
    assert row == '"บูธยิงปืน, ฐาน 2",10\r\n'


def test_results_are_translated_for_humans():
    """คนที่เปิดไฟล์คือทีมงาน ไม่ใช่โปรแกรมเมอร์ — ห้ามเห็น rotating_code_mismatch"""
    assert RESULT_TH["ok"] == "ผ่าน"
    assert RESULT_TH["duplicate"] == "เข้าแล้ว (สแกนซ้ำ)"
    # ผลลัพธ์ทุกแบบที่ backend สร้างได้ต้องมีคำแปล ไม่งั้นหลุดเป็น code ดิบ
    from app.models.schemas import CheckinOut
    known = CheckinOut.model_fields["result"].annotation.__args__
    missing = [r for r in known if r not in RESULT_TH and r != "queued"]
    assert not missing, f"ยังไม่มีคำแปลไทยของผลลัพธ์: {missing}"


def test_sources_are_translated():
    assert SOURCE_TH["qr"] == "สแกน QR"
    assert SOURCE_TH["manual"] == "เช็คด้วยมือจากรายชื่อ"


def test_every_coin_reason_has_a_thai_label():
    """ที่มาของเหรียญที่โค้ดสร้างได้จริง ต้องมีคำแปลครบ ไม่งั้นหลุดเป็น code ดิบ"""
    from app.routers.exports import REASON_TH
    for reason in ("checkin", "staff_grant", "admin_adjust", "ig_wall", "ig_wall_refund"):
        assert reason in REASON_TH, f"ยังไม่มีคำแปลไทยของ reason={reason}"


def test_thailand_offset_is_fixed_at_plus_seven():
    """ใช้ offset คงที่แทน ZoneInfo — ไม่ต้องพึ่ง tzdata ที่อาจไม่มีใน image"""
    assert TH.utcoffset(None).total_seconds() == 7 * 3600
