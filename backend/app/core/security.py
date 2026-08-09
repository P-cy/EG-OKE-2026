"""JWT, HMAC, TOTP, hashing — ของที่พลาดแล้วเจ็บ"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from ulid import ULID

from app.core.config import settings


# ── JWT ────────────────────────────────────────────────────────────────
def create_access_token(user_id: str, roles: list[str]) -> tuple[str, str, int]:
    """คืน (token, jti, expires_in)

    ห้ามใส่ email หรือ points ลงไป — client ถอด base64 อ่านได้ และค่าจะ stale
    """
    jti = str(ULID())
    now = int(time.time())
    exp = now + settings.ACCESS_TOKEN_TTL_SECONDS
    payload = {
        "sub": user_id,
        "roles": roles,
        "jti": jti,
        "iat": now,
        "exp": exp,
        "ver": settings.TOKEN_VERSION,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, jti, settings.ACCESS_TOKEN_TTL_SECONDS


def decode_access_token(token: str) -> dict[str, Any]:
    """raise jwt.PyJWTError ถ้าไม่ผ่าน"""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub", "jti"]},
    )
    # ★ ปุ่ม kill-switch: bump TOKEN_VERSION แล้ว token เก่าทุกใบใช้ไม่ได้ทันที
    if payload.get("ver") != settings.TOKEN_VERSION:
        raise jwt.InvalidTokenError("token version mismatch")
    return payload


# ── Refresh token ──────────────────────────────────────────────────────
def new_refresh_token() -> tuple[str, str]:
    """คืน (raw, hash) — เก็บเฉพาะ hash ลง DB เท่านั้น

    ถ้า DB รั่วแล้วเก็บ token ดิบ = ผู้โจมตี login เป็นใครก็ได้
    """
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)


# ── QR signing (HMAC) ──────────────────────────────────────────────────
QR_PREFIX = "EGOKE2"


def build_qr_payload(ticket_code: str, issued_ts: int | None = None) -> str:
    """สร้าง payload สำหรับ QR

    รูปแบบ: EGOKE2:<ver>:<ticket_code>:<issued_ts>:<sig>
    scanner ตรวจ signature ได้เองโดยไม่ต้องต่อเน็ต ← นี่คือเหตุผลที่ใช้ HMAC
    """
    ts = issued_ts or int(time.time())
    body = f"{QR_PREFIX}:{settings.QR_VERSION}:{ticket_code}:{ts}"
    sig = _qr_sign(body)
    return f"{body}:{sig}"


def _qr_sign(body: str) -> str:
    mac = hmac.new(settings.QR_SIGNING_KEY.encode(), body.encode(), hashlib.sha256).digest()
    # ตัดเหลือ 16 bytes (128-bit) → QR เล็กลง สแกนเร็วขึ้น ยังปลอดภัยพอ
    return base64.urlsafe_b64encode(mac[:16]).decode().rstrip("=")


def verify_qr_payload(payload: str) -> tuple[bool, str | None, str]:
    """คืน (valid, ticket_code, reason)"""
    parts = payload.split(":")
    if len(parts) != 5 or parts[0] != QR_PREFIX:
        return False, None, "malformed"
    _, ver, ticket_code, ts, sig = parts
    try:
        if int(ver) != settings.QR_VERSION:
            return False, ticket_code, "wrong_version"
    except ValueError:
        return False, None, "malformed"

    expected = _qr_sign(f"{QR_PREFIX}:{ver}:{ticket_code}:{ts}")
    # ★ compare_digest — ห้ามใช้ == เพราะเปิดช่อง timing attack
    if not hmac.compare_digest(expected, sig):
        return False, ticket_code, "invalid_sig"
    return True, ticket_code, "ok"


# ── TOTP (rotating code กันคนแคปหน้าจอส่งต่อ) ─────────────────────────
def totp_secret_for(ticket_code: str) -> bytes:
    return hmac.new(settings.TOTP_KEY.encode(), ticket_code.encode(), hashlib.sha256).digest()


def totp_now(ticket_code: str, at: int | None = None) -> str:
    return _totp(totp_secret_for(ticket_code), (at or int(time.time())) // settings.TOTP_PERIOD)


def totp_verify(ticket_code: str, code: str, at: int | None = None) -> bool:
    """ยอมรับ ±TOTP_WINDOW period เผื่อนาฬิกาเครื่อง scanner เพี้ยน

    ⚠️ ถ้าเปิด STRICT_QR_MODE ต้องมั่นใจว่า scanner sync NTP แล้ว
       ไม่งั้นจะปฏิเสธทุกคนหน้าประตู
    """
    counter = (at or int(time.time())) // settings.TOTP_PERIOD
    secret = totp_secret_for(ticket_code)
    for drift in range(-settings.TOTP_WINDOW, settings.TOTP_WINDOW + 1):
        if hmac.compare_digest(_totp(secret, counter + drift), code):
            return True
    return False


def _totp(secret: bytes, counter: int, digits: int = 6) -> str:
    msg = struct.pack(">Q", counter)
    digest = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


# ── Privacy helpers ────────────────────────────────────────────────────
def hash_ip(ip: str) -> str:
    """PDPA: ห้ามเก็บ IP ดิบ"""
    return hashlib.sha256((ip + settings.IP_PEPPER).encode()).hexdigest()[:32]


def new_ticket_code() -> str:
    """รหัสบัตร 1 ใบต่อคนทั้งงาน — ไม่ฝัง event_day แล้ว (เดิมคือ EGOKE26-D{day}-...)"""
    return f"EGOKE26-{secrets.token_hex(4).upper()}"
