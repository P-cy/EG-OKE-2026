"""โควตาการจ่ายเหรียญ — กันเหรียญเฟ้อและกัน staff จ่ายให้พวกพ้อง

★ ทำไมต้องมี:
  เหรียญเข้าระบบได้ 4 ทาง — เช็คอิน (10/วัน ปิดด้วย dedupe), กิจกรรม (จำกัดครั้ง/คน),
  วงล้อ (EV ติดลบ + 3 ครั้งต่อคน), และ staff จ่ายที่บูธ
  สามทางแรกมีเพดานในตัวอยู่แล้ว **ทางที่สี่ไม่มีเลย**
  staff คนเดียวจ่าย 1000 ทุก 20 วิ = 180,000 เหรียญต่อชั่วโมงให้คนเดียว
  ไม่มีอะไรหยุด และไม่มีใครรู้จนกว่าจะเปิดดูอันดับแล้วเห็นคนแปลกๆ อยู่บนสุด

★ สามชั้น แต่ละชั้นปิดคนละช่องโหว่:

  1. ต่อครั้ง       — กันพิมพ์ผิดหลัก (ตั้งใจ 100 พิมพ์ 1000)
  2. staff → คนเดียวกัน/วัน — ★ ชั้นที่กัน "จ่ายให้เพื่อน" โดยตรง
                       เพื่อนสนิทคนหนึ่งได้จาก staff คนนั้นได้ไม่เกินโควตานี้
  3. คนหนึ่งรับรวม/วัน  — ★ ชั้นที่กัน "ไล่เก็บจาก staff หลายคน"
                       ชั้นที่ 2 กันได้ทีละคน แต่ถ้ามี staff รู้จัก 20 คน
                       ก็ยังรวมกันได้เยอะ ชั้นนี้ปิดท้าย ไม่ว่ามาจากใคร
  4. staff คนหนึ่งจ่ายรวม/วัน — เบรกเกอร์กันของหลุดมือ (ตั้งหลวมๆ ไม่ให้ขวางบูธที่คนเยอะจริง)

★ นับตามปฏิทินไทย ไม่ใช่ UTC — ไม่งั้นโควตารีเซ็ตตอน 7 โมงเช้าซึ่งอยู่กลางงาน
"""
from dataclasses import dataclass

from bson import ObjectId

from app.core.config import settings
from app.core.observability import log
from app.core.redis_client import get_redis
from app.core.timeutil import th_date_key

TTL = 60 * 60 * 48   # เก็บ 2 วัน — พอให้ข้ามคืนแล้วยังอ่านย้อนได้


def _k_staff(staff_id: str, day: str) -> str:
    return f"grant:staff:{staff_id}:{day}"


def _k_pair(staff_id: str, user_id: str, day: str) -> str:
    return f"grant:pair:{staff_id}:{user_id}:{day}"


def _k_recv(user_id: str, day: str) -> str:
    return f"grant:recv:{user_id}:{day}"


@dataclass
class LimitCheck:
    ok: bool
    message: str = ""
    limit_kind: str = ""      # "per_scan" | "pair" | "receive" | "staff_daily"
    used: int = 0
    cap: int = 0


async def reserve(staff_id: ObjectId, user_id: ObjectId, amount: int) -> LimitCheck:
    """จองโควตาก่อนจ่ายจริง — ผ่านแล้วค่อยเรียก coins.award()

    ★ ต้องจอง "ก่อน" จ่าย ไม่ใช่บันทึกหลังจ่าย
      ถ้านับหลังจ่าย ยอดที่เกินโควตาก็เข้ากระเป๋าไปแล้ว ต้องไปตามถอนทีหลัง

    ★ ถ้า award ล้มเหลวภายหลัง ต้องเรียก release() คืน ไม่งั้นโควตาหายฟรี

    ★ ใช้ INCRBY แล้วเทียบ ไม่ใช่ GET แล้วเทียบแล้วค่อย SET
      แบบหลังเป็น TOCTOU — สแกนพร้อมกันสองเครื่องผ่านด่านทั้งคู่แล้วจ่ายทั้งคู่
    """
    if amount > settings.STAFF_GRANT_MAX_PER_SCAN:
        return LimitCheck(
            False,
            f"จ่ายได้สูงสุด {settings.STAFF_GRANT_MAX_PER_SCAN} เหรียญต่อครั้ง",
            "per_scan", 0, settings.STAFF_GRANT_MAX_PER_SCAN,
        )

    day = th_date_key()
    sid, uid = str(staff_id), str(user_id)
    r = get_redis()

    # เรียงจากด่านที่ "แคบที่สุด" ไปกว้างสุด — ชนด่านแคบก่อนจะได้ไม่ต้องจองด่านอื่น
    ladder = [
        (_k_pair(sid, uid, day), settings.STAFF_GRANT_PER_USER_DAILY, "pair",
         "คุณจ่ายให้คนนี้ครบโควตาวันนี้แล้ว — ให้ staff คนอื่นจ่ายแทน หรือแจ้ง admin"),
        (_k_recv(uid, day), settings.USER_GRANT_RECEIVE_DAILY, "receive",
         "คนนี้รับเหรียญจากบูธครบโควตาวันนี้แล้ว — พรุ่งนี้รับได้ใหม่"),
        (_k_staff(sid, day), settings.STAFF_GRANT_DAILY_BUDGET, "staff_daily",
         "คุณจ่ายเหรียญครบโควตาของวันนี้แล้ว — แจ้ง admin เพื่อขอเพิ่ม"),
    ]

    taken: list[str] = []
    for key, cap, kind, msg in ladder:
        used = await r.incrby(key, amount)
        await r.expire(key, TTL)
        if used > cap:
            # เกิน → คืนที่เพิ่งจองของ key นี้ แล้วคืนของ key ก่อนหน้าทั้งหมด
            await r.decrby(key, amount)
            for done in taken:
                await r.decrby(done, amount)
            log.warning(
                "grant_limit_hit", kind=kind, staff_id=sid, user_id=uid,
                amount=amount, used=used - amount, cap=cap,
            )
            return LimitCheck(False, msg, kind, used - amount, cap)
        taken.append(key)

    return LimitCheck(True)


async def release(staff_id: ObjectId, user_id: ObjectId, amount: int) -> None:
    """คืนโควตาที่จองไว้ — เรียกเมื่อจ่ายไม่สำเร็จ"""
    day = th_date_key()
    sid, uid = str(staff_id), str(user_id)
    r = get_redis()
    p = r.pipeline()
    p.decrby(_k_pair(sid, uid, day), amount)
    p.decrby(_k_recv(uid, day), amount)
    p.decrby(_k_staff(sid, day), amount)
    await p.execute()


async def usage(staff_id: ObjectId | None = None, user_id: ObjectId | None = None) -> dict:
    """ยอดที่ใช้ไปวันนี้ — เอาไปโชว์บนหน้าสแกนและหน้า admin"""
    day = th_date_key()
    r = get_redis()
    out: dict = {"day": day}
    if staff_id:
        used = await r.get(_k_staff(str(staff_id), day))
        out["staff_used"] = int(used or 0)
        out["staff_cap"] = settings.STAFF_GRANT_DAILY_BUDGET
    if user_id:
        used = await r.get(_k_recv(str(user_id), day))
        out["user_received"] = int(used or 0)
        out["user_cap"] = settings.USER_GRANT_RECEIVE_DAILY
    return out


async def reset_staff_budget(staff_id: ObjectId) -> int:
    """admin ล้างโควตาให้ staff — บูธที่คนเยอะจริงจนชนเพดาน

    คืนยอดที่ล้างไป เพื่อให้ audit log บันทึกได้ว่าล้างตอนใช้ไปเท่าไหร่
    """
    day = th_date_key()
    r = get_redis()
    key = _k_staff(str(staff_id), day)
    before = int(await r.get(key) or 0)
    await r.delete(key)
    return before
