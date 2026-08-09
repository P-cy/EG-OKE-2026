"""FastAPI dependencies — auth, roles, feature flags"""
import json
from dataclasses import dataclass
from typing import Annotated

import jwt
from bson import ObjectId
from fastapi import Depends, Header, Query, Request

from app.core.db import Col
from app.core.errors import degraded, forbidden, unauthorized
from app.core.redis_client import K, get_redis
from app.core.security import decode_access_token


@dataclass
class CurrentUser:
    id: str
    roles: list[str]
    jti: str

    @property
    def oid(self) -> ObjectId:
        return ObjectId(self.id)

    def has(self, *roles: str) -> bool:
        return any(r in self.roles for r in roles)


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized()
    token = authorization[7:]

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise unauthorized("เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่")
    except jwt.PyJWTError:
        raise unauthorized("โทเคนไม่ถูกต้อง")

    jti = payload["jti"]
    # ★ denylist check — logout แล้วต้องใช้ token เดิมไม่ได้
    if await get_redis().exists(K.JWT_DENY.format(jti=jti)):
        raise unauthorized("เซสชันถูกยกเลิกแล้ว")

    user = CurrentUser(id=payload["sub"], roles=payload.get("roles", []), jti=jti)
    request.state.user_id = user.id
    return user


async def get_optional_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser | None:
    if not authorization:
        return None
    try:
        return await get_current_user(request, authorization)
    except Exception:
        return None


async def get_current_user_from_query(
    token: Annotated[str, Query()],
) -> CurrentUser:
    """auth ผ่าน query param — สำหรับ SSE/EventSource ที่ส่ง Authorization header ไม่ได้

    เหมือน get_current_user ทุกอย่าง แค่เปลี่ยนแหล่ง token จาก header → query
    (token จะรั่วใน log บ้าง แต่ access token TTL 15 นาที ยอมรับได้)
    """
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise unauthorized("เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่")
    except jwt.PyJWTError:
        raise unauthorized("โทเคนไม่ถูกต้อง")

    jti = payload["jti"]
    if await get_redis().exists(K.JWT_DENY.format(jti=jti)):
        raise unauthorized("เซสชันถูกยกเลิกแล้ว")
    return CurrentUser(id=payload["sub"], roles=payload.get("roles", []), jti=jti)


def require_roles(*roles: str):
    """ใช้เป็น dependency: `_=Depends(require_roles("admin"))`"""

    async def _check(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if not user.has(*roles, "superadmin"):
            raise forbidden(
                "INSUFFICIENT_ROLE",
                "คุณไม่มีสิทธิ์เข้าถึงส่วนนี้",
                "Insufficient permissions",
            )
        return user

    return _check


require_staff = require_roles("staff", "admin")
require_admin = require_roles("admin")


# ── System config / feature flags ─────────────────────────────────────
DEFAULT_CONFIG = {
    "maintenance_mode": False,
    "read_only_mode": False,
    "features": {
        "voting": True,
        "wheel": True,
        "ig_submission": True,
        "checkin": True,
        "quests": True,
    },
    "announcement": {"text": "", "level": "info"},
}


async def get_config() -> dict:
    """cache 5 วินาที — admin กดปิดฟีเจอร์แล้วมีผลใน 5 วิ โดยไม่ต้อง deploy"""
    r = get_redis()
    cached = await r.get(K.SYS_CONFIG)
    if cached:
        return json.loads(cached)

    doc = await Col.system_config().find_one({"_id": "global"}) or {}
    cfg = {**DEFAULT_CONFIG, **{k: v for k, v in doc.items() if k != "_id"}}
    await r.set(K.SYS_CONFIG, json.dumps(cfg, default=str), ex=5)
    return cfg


def require_feature(name: str, thai_label: str):
    """กันไม่ให้ฟีเจอร์ที่ถูกปิดถูกเรียกใช้"""

    async def _check(cfg: Annotated[dict, Depends(get_config)]) -> None:
        if cfg.get("maintenance_mode"):
            raise degraded("ทั้งหมด (ปิดปรับปรุง)")
        if not cfg.get("features", {}).get(name, True):
            raise degraded(thai_label)

    return _check


async def require_writable(cfg: Annotated[dict, Depends(get_config)]) -> None:
    """ปุ่มฉุกเฉิน: read_only_mode = ทุกคนอ่านได้ แต่เขียนไม่ได้

    ใช้ตอน "ทุกอย่างพัง ไม่รู้สาเหตุ" — หยุดเลือดก่อน แล้วค่อยหาสาเหตุ
    """
    if cfg.get("read_only_mode"):
        raise degraded("การบันทึกข้อมูล (โหมดอ่านอย่างเดียว)")


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
CurrentUserQueryDep = Annotated[CurrentUser, Depends(get_current_user_from_query)]
OptionalUserDep = Annotated[CurrentUser | None, Depends(get_optional_user)]
ConfigDep = Annotated[dict, Depends(get_config)]
