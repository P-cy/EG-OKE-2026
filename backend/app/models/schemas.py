"""Pydantic models — ทุก input จาก client ต้องผ่านที่นี่

⚠️ กฎเหล็ก: ห้ามส่ง raw dict จาก request body เข้า Mongo query โดยตรง
   ต้องผ่าน model เหล่านี้เสมอ (กัน NoSQL injection แบบ {"$ne": null})
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

OBJECT_ID = r"^[0-9a-fA-F]{24}$"
SLUG = r"^[a-z0-9\-]{1,32}$"


# ── Auth ───────────────────────────────────────────────────────────────
class GoogleCallbackIn(BaseModel):
    code: str = Field(min_length=10, max_length=2048)
    state: str = Field(min_length=8, max_length=128)


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    # ★ ชื่อจริงจาก Google — เก็บมาตั้งแต่ login แต่ไม่เคยส่งออกมา
    #   สำคัญขึ้นมากเมื่อเปิดรับอีเมลทุก domain: อีเมลไม่บอกว่าใครเป็นใครแล้ว
    #   staff ที่ประตูต้องมีชื่อจริงไว้เทียบกับบัตรนักศึกษา
    full_name: str | None = None
    avatar_url: str | None = None
    instagram_handle: str | None = None
    faculty: str | None = None
    department: str | None = None
    student_id: str | None = None
    roles: list[str]
    coins_balance: int = 0
    rank: int | None = None
    needs_onboarding: bool = False


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserPublic


# ── Profile ────────────────────────────────────────────────────────────
class ProfileUpdateIn(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=40)
    instagram_handle: str | None = Field(None, pattern=r"^[A-Za-z0-9._]{1,30}$")
    faculty: str | None = Field(None, pattern=r"^[A-Za-z]{2,4}$", description="รหัสคณะ เช่น EG, SC")
    department: str | None = Field(None, pattern=r"^[A-Za-z]{2,4}$", description="รหัสภาค/สาขา เช่น CO, IC")
    student_id: str | None = Field(None, pattern=r"^\d{7}$", description="รหัสนักศึกษามหิดล 7 หลัก")
    consent_photo: bool | None = None

    @field_validator("display_name")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        return v.strip() if v else v


# ── Avatar ─────────────────────────────────────────────────────────────
class AvatarUploadIn(BaseModel):
    # base64 ของรูปที่ resize แล้ว (~15-30KB สำหรับ 256px JPEG)
    # cap ที่ ~220KB กันคนส่งรูปใหญ่ดิบๆ มาเก็บใน Mongo
    image_data: str = Field(min_length=100, max_length=300_000)
    mime: Literal["image/jpeg", "image/png", "image/webp"] = "image/jpeg"


# ── Tickets / Check-in ─────────────────────────────────────────────────
class QROut(BaseModel):
    payload: str
    ticket_code: str
    event_day: int = 0           # 0 = บัตรเดียวทั้งงาน (legacy ใช้สำหรับ 1 บัตร/วัน)
    status: str
    checked_in_days: list[int] = []   # วันที่เช็คอินไปแล้ว — คนเข้างานเห็นเองว่าเข้าวันไหนแล้ว
    rotating_code: str | None = None
    rotates_in: int | None = None


class CheckinIn(BaseModel):
    """★ `payload` รับได้ 3 แบบ (ดู checkin.resolve_ticket)
    1. QR payload เต็ม  `EGOKE2:1:EGOKE26-XXXXXXXX:<ts>:<sig>`  ← กล้องสแกนได้แบบนี้
    2. รหัสบัตร        `EGOKE26-XXXXXXXX`                      ← staff พิมพ์จากจอผู้เข้างาน
    3. รหัสนักศึกษา     `6913099` (7 หลัก)                       ← กรณีมือถือแบตหมด/เปิดบัตรไม่ได้
    min_length=6 เพราะรหัสนักศึกษาสั้นสุด — ห้ามตั้ง 20 ไม่งั้นแบบ 2/3 โดน 422 ตั้งแต่ต้นทาง
    """
    payload: str = Field(min_length=6, max_length=256)
    rotating_code: str | None = Field(None, pattern=r"^\d{6}$")
    event_day: int = Field(ge=1, le=3, description="วันที่เช็คอิน 1/2/3 — staff เลือกที่เครื่องสแกน")
    gate: str = Field(default="MAIN", max_length=32)
    device_id: str = Field(max_length=64)
    scanned_at: datetime | None = None


class CheckinOut(BaseModel):
    result: Literal[
        "ok", "duplicate", "invalid_sig", "revoked",
        "wrong_day", "expired", "rotating_code_mismatch", "not_found", "no_ticket",
    ]
    event_day: int | None = None
    # ★ บอก staff ว่าจับคู่ได้จากอะไร: "qr" | "ticket_code" | "student_id"
    matched_by: str | None = None
    # ★ ข้อความไทยพร้อมอ่าน — scanner โชว์ตรงนี้ ไม่ต้องแปล code เอง
    message: str | None = None
    user: dict | None = None
    ticket: dict | None = None
    coins_awarded: int = 0
    checked_in_at: datetime | None = None
    checked_in_gate: str | None = None


class CheckinBatchIn(BaseModel):
    items: list[CheckinIn] = Field(max_length=100)  # จำกัดกัน payload บวม


class ManualCheckinIn(BaseModel):
    """admin เช็คชื่อจากรายชื่อ (ไม่ใช้ QR)"""
    user_id: str = Field(pattern=OBJECT_ID)
    event_day: int = Field(ge=1, le=3)
    gate: str = Field(default="ADMIN", max_length=32)


class AttendeeRow(BaseModel):
    id: str
    email: EmailStr
    display_name: str | None = None
    full_name: str | None = None      # ชื่อจริงจาก Google — ใช้ยืนยันตัวตนที่ประตู
    student_id: str | None = None
    faculty: str | None = None
    department: str | None = None
    ticket_code: str | None = None
    ticket_status: str | None = None
    checked_in_days: list[int] = []
    last_checked_in_at: datetime | None = None
    coins_balance: int = 0


# ── Quests (บูธกิจกรรม — staff สแกน QR ผู้เข้างานเพื่อจ่ายเหรียญ) ──────
class UserRolesIn(BaseModel):
    """ตั้งสิทธิ์ — ส่งมาเป็นชุดเต็ม ไม่ใช่ทีละอัน (ตั้งซ้ำได้ ผลเหมือนเดิม)

    ★ จำกัดค่าที่รับได้ด้วย Literal — ไม่งั้นพิมพ์ผิดเป็น "adnim" ก็บันทึกลง DB
      เงียบๆ แล้วคนนั้นไม่ได้สิทธิ์อะไรเลยโดยไม่มีใครรู้ว่าทำไม
    ★ participant ไม่ต้องส่งมา ระบบใส่ให้เองเสมอ
    ★ superadmin ตั้งผ่าน API ไม่ได้ — ต้องแก้ใน DB ตรงๆ เท่านั้น
    """
    roles: list[Literal["staff", "admin"]] = Field(default_factory=list, max_length=2)


class QuestIn(BaseModel):
    quest_key: str = Field(pattern=SLUG, description="รหัสสั้น a-z0-9- ห้ามซ้ำ")
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    coins: int = Field(ge=0, le=1000)
    status: Literal["open", "closed"] = "open"
    max_per_user: int = Field(default=1, ge=1, le=20, description="คนหนึ่งรับได้กี่ครั้ง")
    sort_order: int = 0


class QuestPatch(BaseModel):
    """แก้บางฟิลด์ — ไม่ส่งมา = ไม่แก้ (quest_key เปลี่ยนไม่ได้)"""
    title: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = Field(None, max_length=300)
    coins: int | None = Field(None, ge=0, le=1000)
    status: Literal["open", "closed"] | None = None
    max_per_user: int | None = Field(None, ge=1, le=20)
    sort_order: int | None = None


class QuestPublic(BaseModel):
    quest_key: str
    title: str
    description: str = ""
    coins: int
    status: str
    max_per_user: int = 1
    sort_order: int = 0
    my_claims: int = 0          # ผู้ใช้คนนี้รับไปแล้วกี่ครั้ง
    claimed_count: int = 0      # (admin) มีคนรับไปแล้วกี่ครั้งรวม


class CoinGrantIn(BaseModel):
    """staff จ่ายเหรียญให้คนเข้างานที่บูธ — ไม่ผูกกับกิจกรรมใด

    บูธเก็บค่าเล่นเป็นเงินสดเอง ระบบไม่ยุ่ง หน้าที่ของระบบคือจ่ายรางวัลอย่างเดียว
    staff เลือกจำนวนแล้วสแกน — ไม่ต้องมาเลือกว่าบูธไหนก่อน
    """
    payload: str = Field(min_length=6, max_length=256)   # QR / รหัสบัตร / รหัสนักศึกษา
    # ★ เพดานต่อครั้ง — กันพิมพ์ 1000 ทั้งที่ตั้งใจพิมพ์ 100
    #   ผิดพลาดแบบนี้ถอนคืนได้ก็จริง แต่ต้องมีคนสังเกตเห็นก่อน ซึ่งมักไม่มี
    amount: int = Field(ge=1, le=1000)
    note: str = Field(default="", max_length=100)        # บูธไหน/เหตุผล (ไม่บังคับ)
    device_id: str = Field(default="booth", max_length=64)


class CoinGrantOut(BaseModel):
    """หน้าตาเดียวกับ CheckinOut เพื่อให้เครื่องสแกนใช้จอผลลัพธ์ร่วมกันได้"""
    result: Literal[
        "ok", "duplicate", "limit_reached",
        "not_found", "no_ticket", "invalid_sig", "revoked", "error",
    ]
    message: str | None = None
    matched_by: str | None = None
    coins_awarded: int = 0
    new_balance: int = 0
    user: dict | None = None
    # ★ ชนโควตาอันไหน — staff ต้องรู้ว่าให้รอ ให้เปลี่ยนคน หรือให้ไปตาม admin
    limit_kind: str | None = None    # "per_scan" | "pair" | "receive" | "staff_daily"
    limit_used: int = 0
    limit_cap: int = 0
    # ยอดที่ staff คนนี้จ่ายไปแล้ววันนี้ — โชว์บนเครื่องสแกนตลอดเวลา
    staff_used_today: int = 0
    staff_cap_today: int = 0


class QuestClaimIn(BaseModel):
    """staff สแกนที่บูธ — payload รับได้ 3 แบบเหมือน /checkin"""
    quest_key: str = Field(pattern=SLUG)
    payload: str = Field(min_length=6, max_length=256)
    device_id: str = Field(default="booth", max_length=64)


class QuestClaimOut(BaseModel):
    result: Literal["ok", "duplicate", "quest_closed", "not_found", "no_ticket", "invalid_sig"]
    message: str | None = None
    matched_by: str | None = None
    quest_key: str | None = None
    quest_title: str | None = None
    coins_awarded: int = 0
    user: dict | None = None
    claims_used: int = 0
    max_per_user: int = 1


# ── Voting ─────────────────────────────────────────────────────────────
class VoteIn(BaseModel):
    round_key: str = Field(pattern=SLUG)
    artist_id: str = Field(pattern=OBJECT_ID)


class VoteOut(BaseModel):
    accepted: bool
    round_key: str
    artist_id: str
    already_voted: bool
    results_visible: bool = False


class ArtistPublic(BaseModel):
    id: str
    name: str
    image_url: str | None = None
    sort_order: int = 0


class VoteRoundPublic(BaseModel):
    round_key: str
    title: str
    status: str
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    results_public: bool
    max_votes_per_user: int
    candidates: list[ArtistPublic]
    my_vote: str | None = None


# ── Instagram (ระบบจอใหญ่) ────────────────────────────────────────────
class IGSubmitIn(BaseModel):
    """อัปโหลดรูป + ชื่อ IG + แคปชัน เพื่อขึ้นจอใหญ่ (จ่ายเหรียญ)"""
    image_data: str = Field(min_length=100, max_length=4_000_000, description="base64 รูป")
    instagram_handle: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9._]{1,30}$")
    caption: str | None = Field(None, max_length=200)


class IGSubmissionOut(BaseModel):
    id: str
    shortcode: str
    status: str
    coins_awarded: int = 0
    submitted_at: datetime
    reject_reason: str | None = None


# ── Wheel ──────────────────────────────────────────────────────────────
class SpinIn(BaseModel):
    client_seed: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    nonce: int = Field(ge=1, le=1000)


class SpinOut(BaseModel):
    spin_id: str
    result_segment_id: str
    segment_index: int
    label: str
    prize_type: str
    coins_won: int = 0
    coins_spent: int = 0
    coins_balance: int = 0
    proof: dict


# ── Admin ──────────────────────────────────────────────────────────────
class CoinAdjustIn(BaseModel):
    amount: int = Field(ge=-10000, le=10000)
    reason: str = Field(default="admin_adjust", pattern=r"^[a-z0-9_\-]{1,32}$")
    note: str = Field(min_length=1, max_length=200)  # ★ บังคับ — audit trail ต้องอ่านรู้เรื่อง


class ConfigPatchIn(BaseModel):
    maintenance_mode: bool | None = None
    read_only_mode: bool | None = None
    features: dict[str, bool] | None = None
    announcement: dict | None = None


# ── Top-up (เติมเหรียญ) ────────────────────────────────────────────────
# ลบระบบเติมเงิน QR/SlipOK ออกแล้ว — staff เพิ่มเหรียญให้ผู้ใช้เองผ่าน /admin/users

