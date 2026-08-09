"""เวลาไทย — ที่เดียว ใช้ทุกที่

★ ใช้ offset คงที่ +07:00 ไม่ใช่ ZoneInfo("Asia/Bangkok")
  ZoneInfo ต้องมี tzdata ติดมากับ image ถ้าไม่มีจะพังตอน runtime เท่านั้น
  (import ผ่าน เทสต์ผ่าน แต่พอเรียกใช้จริงแล้ว 500) ไทยไม่มี DST อยู่แล้ว
"""
from datetime import datetime, timedelta, timezone

TH = timezone(timedelta(hours=7))


def th_now() -> datetime:
    return datetime.now(TH)


def th_date_key(when: datetime | None = None) -> str:
    """คีย์ของ "วันนี้" ตามปฏิทินไทย — ใช้กับโควตารายวัน

    ★ ต้องตัดวันตามเวลาไทย ไม่ใช่ UTC
      งานเลิก 5 ทุ่ม = 16:00 UTC ยังเป็นวันเดิม แต่ถ้าตัดด้วย UTC
      โควตาจะรีเซ็ตตอน 7 โมงเช้าซึ่งอยู่กลางงานพอดี
    """
    return (when or th_now()).astimezone(TH).strftime("%Y%m%d")
