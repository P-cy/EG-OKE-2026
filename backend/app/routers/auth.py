"""Google OAuth + JWT session"""
import json
import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response

from app.core import ratelimit
from app.core.config import settings
from app.core.db import Col
from app.core.deps import CurrentUserDep
from app.core.errors import AppError, forbidden, unauthorized
from app.core.redis_client import K, get_redis
from app.core.security import (
    create_access_token, decode_access_token, hash_token,
    new_refresh_token, refresh_expiry,
)
from app.models.schemas import GoogleCallbackIn, TokenOut, UserPublic
from app.services import google_oauth
from app.services.profile import needs_onboarding

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "rt"
COOKIE_PATH = "/v1/auth"


@router.get("/google/login")
async def google_login(request: Request, redirect_uri: str | None = None):
    """เริ่ม OAuth flow — คืน URL ให้ frontend redirect ไป"""
    await ratelimit.check("auth", ratelimit.client_ip(request))

    verifier, challenge = google_oauth.make_pkce()
    state = secrets.token_urlsafe(24)

    await get_redis().set(
        K.OAUTH_STATE.format(state=state),
        json.dumps({"verifier": verifier, "redirect_uri": redirect_uri}),
        ex=600,
    )
    return {
        "authorize_url": google_oauth.build_auth_url(state, challenge, redirect_uri),
        "state": state,
    }


@router.post("/google/callback", response_model=TokenOut)
async def google_callback(body: GoogleCallbackIn, request: Request, response: Response):
    await ratelimit.check("auth", ratelimit.client_ip(request))

    # ★ GETDEL — state ใช้ได้ครั้งเดียว กัน replay/CSRF
    raw = await get_redis().getdel(K.OAUTH_STATE.format(state=body.state))
    if not raw:
        raise AppError(400, "OAUTH_STATE_INVALID", "เซสชันการเข้าสู่ระบบหมดอายุ กรุณาลองใหม่")
    stored = json.loads(raw)

    profile = await google_oauth.exchange_code(
        body.code, stored["verifier"], stored.get("redirect_uri")
    )

    now = datetime.now(timezone.utc)
    # ★ role จากอีเมล allowlist — promote เท่านั้น ไม่ demote
    #   (กันกรณีมีคนเคยเป็น superadmin แล้วเอาอีเมลออกจากลิสต์ ไม่ควรถูกลดระดับเงียบๆ)
    is_admin_email = profile["email"] in settings.admin_emails
    insert_roles = ["participant", "admin"] if is_admin_email else ["participant"]

    # ★ ดึง user เดิมก่อน upsert — ถ้าเคยอัปโหลด avatar เองไว้ ห้ามให้ Google URL เขียนทับ
    existing = await Col.users().find_one({"google_sub": profile["sub"]}, {"avatar_data": 1})
    has_custom_avatar = bool(existing and existing.get("avatar_data"))

    # ★ upsert ด้วย google_sub ไม่ใช่ email — sub เป็น immutable id
    set_fields = {
        "email": profile["email"],
        "email_domain": profile["email_domain"],
        "full_name": profile["full_name"],
        "last_login_at": now,
        "updated_at": now,
    }
    # ถ้ามี avatar ที่ upload เอง → คง avatar_url ของเราไว้ ไม่เขียนทับด้วย Google URL
    if not has_custom_avatar:
        set_fields["avatar_url"] = profile["avatar_url"]

    update_doc = {
        "$set": set_fields,
        "$setOnInsert": {
            "google_sub": profile["sub"],
            "display_name": profile["given_name"] or profile["email"].split("@")[0],
            "student_id": None,  # ★ ผู้ใช้กรอกเองใน onboarding (email มหิดล format ไม่แน่นอน)
            "roles": insert_roles,
            "status": "active",
            "coins_balance": 0,
            "consent": {},
            "created_at": now,
            "schema_version": 1,
        },
        "$inc": {"login_count": 1},
    }

    # ★ กรณีคนเก่า login ใหม่ และอีเมลอยู่ใน allowlist แต่ยังไม่มี role admin → promote
    #   ทำเป็น update แยกหลัง upsert เพราะ $setOnInsert ทำงานเฉพาะตอน insert
    user = await Col.users().find_one_and_update(
        {"google_sub": profile["sub"]},
        update_doc,
        upsert=True,
        return_document=True,
    )

    if is_admin_email and "admin" not in (user.get("roles") or []):
        user = await Col.users().find_one_and_update(
            {"_id": user["_id"]},
            {"$addToSet": {"roles": "admin"}},
            return_document=True,
        )

    if user.get("status") in ("suspended", "banned"):
        raise forbidden("ACCOUNT_SUSPENDED", "บัญชีนี้ถูกระงับการใช้งาน")

    token, jti, ttl = create_access_token(str(user["_id"]), user.get("roles", []))
    raw_rt, rt_hash = new_refresh_token()

    await Col.refresh_tokens().insert_one({
        "user_id": user["_id"],
        "token_hash": rt_hash,
        "family_id": secrets.token_hex(16),
        "revoked": False,
        "expires_at": refresh_expiry(),
        "created_at": now,
    })
    _set_refresh_cookie(response, raw_rt)

    # cache meta สำหรับ leaderboard (ไม่ต้อง query Mongo ตอน render top-10)
    await get_redis().set(
        K.USER_META.format(uid=str(user["_id"])),
        json.dumps({
            "display_name": user.get("display_name"),
            "avatar_url": user.get("avatar_url"),
            "instagram_handle": user.get("instagram_handle"),
        }),
        ex=3600,
    )

    return TokenOut(
        access_token=token,
        expires_in=ttl,
        user=UserPublic(
            id=str(user["_id"]),
            email=user["email"],
            display_name=user.get("display_name", ""),
            avatar_url=user.get("avatar_url"),
            instagram_handle=user.get("instagram_handle"),
            roles=user.get("roles", []),
            coins_balance=user.get("coins_balance", 0),
            needs_onboarding=needs_onboarding(user),
        ),
    )


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    response: Response,
    rt: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
):
    if not rt:
        raise unauthorized("ไม่พบ refresh token")

    doc = await Col.refresh_tokens().find_one({"token_hash": hash_token(rt)})
    if not doc:
        raise unauthorized("refresh token ไม่ถูกต้อง")

    # ★ reuse detection: ถ้าใบที่ rotate ไปแล้วถูกใช้ซ้ำ = ถูกขโมย
    if doc.get("revoked") or doc.get("replaced_by"):
        await Col.refresh_tokens().update_many(
            {"family_id": doc["family_id"]}, {"$set": {"revoked": True}}
        )
        raise AppError(
            401, "TOKEN_REUSE_DETECTED",
            "ตรวจพบการใช้งานผิดปกติ กรุณาเข้าสู่ระบบใหม่",
            "Token reuse detected — all sessions revoked",
        )

    if doc["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise unauthorized("refresh token หมดอายุ")

    user = await Col.users().find_one({"_id": doc["user_id"]})
    if not user or user.get("status") != "active":
        raise forbidden("ACCOUNT_SUSPENDED", "บัญชีนี้ถูกระงับการใช้งาน")

    # rotate
    raw_new, hash_new = new_refresh_token()
    new_doc = await Col.refresh_tokens().insert_one({
        "user_id": user["_id"],
        "token_hash": hash_new,
        "family_id": doc["family_id"],
        "revoked": False,
        "expires_at": refresh_expiry(),
        "created_at": datetime.now(timezone.utc),
    })
    await Col.refresh_tokens().update_one(
        {"_id": doc["_id"]}, {"$set": {"replaced_by": new_doc.inserted_id}}
    )
    _set_refresh_cookie(response, raw_new)

    token, _jti, ttl = create_access_token(str(user["_id"]), user.get("roles", []))
    return TokenOut(
        access_token=token,
        expires_in=ttl,
        user=UserPublic(
            id=str(user["_id"]),
            email=user["email"],
            display_name=user.get("display_name", ""),
            avatar_url=user.get("avatar_url"),
            instagram_handle=user.get("instagram_handle"),
            roles=user.get("roles", []),
            coins_balance=user.get("coins_balance", 0),
            needs_onboarding=needs_onboarding(user),
        ),
    )


@router.post("/logout")
async def logout(
    user: CurrentUserDep,
    request: Request,
    response: Response,
    rt: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
):
    # denylist access token จนกว่าจะหมดอายุเอง
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            payload = decode_access_token(auth[7:])
            ttl = max(1, payload["exp"] - int(datetime.now(timezone.utc).timestamp()))
            await get_redis().set(K.JWT_DENY.format(jti=payload["jti"]), "1", ex=ttl)
        except Exception:
            pass

    if rt:
        doc = await Col.refresh_tokens().find_one({"token_hash": hash_token(rt)})
        if doc:
            await Col.refresh_tokens().update_many(
                {"family_id": doc["family_id"]}, {"$set": {"revoked": True}}
            )

    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    return {"ok": True}


def _set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        raw,
        httponly=True,                      # ★ JS อ่านไม่ได้ → XSS ขโมยไม่ได้
        secure=settings.is_prod,
        samesite="lax",                     # ★ กัน CSRF
        path=COOKIE_PATH,                   # ★ ส่งเฉพาะ endpoint auth
        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
    )
