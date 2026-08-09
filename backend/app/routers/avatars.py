"""Public avatar endpoint — ส่งรูปโปรไฟล์ของ user

Public (ไม่ต้อง auth) เพราะ avatar คือข้อมูลสาธารณะอยู่แล้ว (รูป Google เดิมก็ public)
ทำให้ <img src> โหลดตรงๆ ได้ และ CDN/Nginx cache ได้
"""
import base64

from bson import ObjectId
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from app.core import ratelimit
from app.core.db import Col
from app.core.errors import not_found

router = APIRouter(prefix="/avatars", tags=["avatars"])

# avatar เปลี่ยนไม่บ่อย → cache 1 ชม และ immutable ตาม ?v= version
# ถ้าเปลี่ยนรูปใหม่ URL เปลี่ยน ?v= ใหม่ → browser ดึงใหม่
_CACHE = "public, max-age=3600, immutable"


@router.get("/{user_id}")
async def get_avatar(user_id: str, request: Request):
    await ratelimit.check_public("live", request)

    # validate ObjectId กัน NoSQL injection (เช่น {"$ne": null})
    if not ObjectId.is_valid(user_id):
        raise not_found("รูปโปรไฟล์")

    doc = await Col.users().find_one(
        {"_id": ObjectId(user_id)},
        {"avatar_data": 1, "avatar_mime": 1, "avatar_url": 1},
    )
    if not doc:
        raise not_found("รูปโปรไฟล์")

    # กรณี 1: มีรูปที่ upload เก็บใน Mongo → ส่ง binary ออก
    # ★ header ต้องใส่ตอนสร้าง Response — เซ็ตที่ `response: Response` ที่ inject มา
    #   จะหายทั้งหมดเมื่อ return Response ใหม่ (ของเดิมทำแบบนั้น = ไม่เคย cache เลย)
    if doc.get("avatar_data"):
        mime = doc.get("avatar_mime", "image/jpeg")
        try:
            img = base64.b64decode(doc["avatar_data"])
        except Exception:
            raise not_found("รูปโปรไฟล์")
        return Response(content=img, media_type=mime, headers={"Cache-Control": _CACHE})

    # กรณี 2: มีแค่ avatar_url จาก Google → redirect ไป (CDN จะ cache)
    if doc.get("avatar_url"):
        return RedirectResponse(
            url=doc["avatar_url"], status_code=302, headers={"Cache-Control": _CACHE}
        )

    raise not_found("รูปโปรไฟล์")
