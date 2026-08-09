"""Google OAuth 2.0 + PKCE

ตรวจสอบครบ 6 ชั้น — ข้ามชั้นไหนก็เปิดช่องให้คนนอกมหาลัยเข้าได้
"""
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import settings
from app.core.errors import AppError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
VALID_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

_jwk_client: PyJWKClient | None = None
_jwk_fetched_at: float = 0.0


def _jwks() -> PyJWKClient:
    """cache JWKS 24 ชม. — ถ้าไม่ cache จะยิง Google ทุก login"""
    global _jwk_client, _jwk_fetched_at
    if _jwk_client is None or time.time() - _jwk_fetched_at > 86400:
        _jwk_client = PyJWKClient(JWKS_URL, cache_keys=True)
        _jwk_fetched_at = time.time()
    return _jwk_client


def make_pkce() -> tuple[str, str]:
    """คืน (code_verifier, code_challenge)"""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def build_auth_url(state: str, code_challenge: str, redirect_uri: str | None = None) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri or settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        # ★ select_account = เปิดหน้าเลือกบัญชีจากลิสต์ (ไม่ใช่หน้ากรอกอีเมล)
        #   ถ้าใส่ hd ไปด้วย Google จะเปิดหน้ากรอกอีเมลแทน — เลยเอาออน
        #   การจำกัด domain ทำฝั่ง server ที่ verify_id_token อยู่แล้ว (ปลอดภัยกว่า hd ที่ปลอมได้)
        "prompt": "select_account",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, code_verifier: str, redirect_uri: str | None = None) -> dict:
    """แลก authorization code → id_token แล้ว verify ครบทุกชั้น"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri or settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
    if resp.status_code != 200:
        raise AppError(
            400, "OAUTH_EXCHANGE_FAILED",
            "แลกเปลี่ยนโทเคนกับ Google ไม่สำเร็จ",
            "Failed to exchange code with Google",
            details={"google_status": resp.status_code},
        )

    id_token = resp.json().get("id_token")
    if not id_token:
        raise AppError(400, "OAUTH_NO_ID_TOKEN", "Google ไม่ได้ส่ง id_token กลับมา")

    return verify_id_token(id_token)


def verify_id_token(id_token: str) -> dict:
    """ตรวจ 6 ชั้น — ข้ามชั้นไหนก็เป็นช่องโหว่"""
    try:
        signing_key = _jwks().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.GOOGLE_CLIENT_ID,   # ชั้น 2: aud
            options={"require": ["exp", "iat", "sub", "email"]},
        )
    except jwt.PyJWTError as e:
        raise AppError(401, "OAUTH_TOKEN_INVALID", "โทเคนจาก Google ไม่ถูกต้อง", str(e))

    # ชั้น 3: issuer
    if claims.get("iss") not in VALID_ISSUERS:
        raise AppError(401, "OAUTH_BAD_ISSUER", "ผู้ออกโทเคนไม่ถูกต้อง")

    # ชั้น 4: email verified — ★ ห้ามลืม
    if not claims.get("email_verified"):
        raise AppError(403, "EMAIL_NOT_VERIFIED", "อีเมลนี้ยังไม่ได้ยืนยันกับ Google")

    # ชั้น 5: domain allowlist
    # ★ ปล่อยว่าง = รับทุก domain (ค่า default ตอนนี้)
    #   เหตุผล: หน้างานคนส่วนใหญ่ไม่ได้ล็อกอินเมลมหิดลไว้ในมือถือ
    #   จะให้ไปล็อกอินใหม่หน้าประตูคือคอขวดที่ทำให้แถวยาว
    #   ตัวตนที่ใช้จริงมาจากชื่อที่กรอกตอน onboarding + ชื่อจริงจาก Google อยู่แล้ว
    #   ถ้าจะกลับไปจำกัดเฉพาะมหิดล ตั้ง ALLOWED_EMAIL_DOMAINS ใน .env
    email = (claims.get("email") or "").lower()
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    allowed = settings.allowed_domains
    if allowed and domain not in allowed:
        raise AppError(
            403, "EMAIL_DOMAIN_NOT_ALLOWED",
            f"อีเมลนี้เข้าใช้งานไม่ได้ ({domain}) กรุณาใช้อีเมลที่กำหนด",
            "Email domain not allowed",
            details={"allowed": sorted(allowed)},
        )

    # ชั้น 6: ต้องมี sub (immutable id) — ใช้ match user ไม่ใช่ email
    if not claims.get("sub"):
        raise AppError(401, "OAUTH_NO_SUB", "โทเคนไม่มี subject id")

    return {
        "sub": claims["sub"],
        "email": email,
        "email_domain": domain,
        "full_name": claims.get("name", ""),
        "given_name": claims.get("given_name", ""),
        "avatar_url": claims.get("picture", ""),
    }
