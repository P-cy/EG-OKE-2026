"""Rate limiting — sliding window counter บน Redis"""
import time
from dataclasses import dataclass

from fastapi import Request

from app.core.errors import rate_limited
from app.core.redis_client import get_redis, get_script


@dataclass(frozen=True)
class Limit:
    requests: int
    window: int  # วินาที


# ⚠️ กฎสำคัญ: endpoint ที่มี auth ให้ key ด้วย user_id เสมอ
# ผู้เข้าร่วมทั้งงานอยู่หลัง WiFi/NAT เดียวกัน — จำกัดต่อ IP จะฆ่าทุกคนพร้อมกัน
LIMITS: dict[str, Limit] = {
    "auth":     Limit(10, 300),    # per IP
    "vote":     Limit(30, 60),     # per user
    "ig":       Limit(5, 86400),   # per user
    "avatar":   Limit(5, 3600),    # per user — อัปโหลดรูปโปรไฟล์
    "spin":     Limit(10, 60),     # per user
    "checkin":  Limit(300, 60),    # per device
    # /live/* — มือถือ poll ทุก 3 วิ = 20 ครั้ง/นาทีต่อคน, จอใหญ่ 6 ครั้ง/นาที
    "live":     Limit(120, 60),    # per user (ถ้า login) — เผื่อไว้ 6 เท่าของการใช้จริง
    # ★ คนที่ยังไม่ login จะแชร์ bucket ตาม IP กัน — หลัง NAT ของงานคือ IP เดียว
    #   จึงต้องเผื่อเยอะ (จอใหญ่ + คนที่ยังอยู่หน้า login + คนที่ token หมดอายุพอดี)
    "live_anon": Limit(3000, 60),  # per IP
    "default":  Limit(100, 60),
}


async def check(scope: str, identity: str) -> None:
    """raise AppError(429) ถ้าเกิน limit"""
    lim = LIMITS.get(scope, LIMITS["default"])
    now = time.time()
    idx = int(now // lim.window)
    elapsed = (now % lim.window) / lim.window

    script = get_script("ratelimit")
    allowed, remaining, retry = await script(
        keys=[f"rl:{scope}:{identity}:{idx}", f"rl:{scope}:{identity}:{idx - 1}"],
        args=[lim.requests, lim.window, f"{elapsed:.4f}"],
    )
    if not int(allowed):
        raise rate_limited(int(retry))


async def check_public(scope: str, request: Request) -> None:
    """rate limit สำหรับ endpoint สาธารณะที่ "คนทั้งงานเรียก"

    ★ นี่คือบั๊กที่ load test เจอ และเป็นบั๊กที่จะทำให้งานล่มจริง:
      /live/snapshot ถูกเรียกจากมือถือทุกเครื่องทุก 3 วิ แต่เดิมนับต่อ IP
      งานนี้ทุกคนอยู่บน WiFi มหาลัยเดียวกัน = ออกเน็ตด้วย IP เดียว
      → 5,000 เครื่อง × 20 ครั้ง/นาที = 100,000 ครั้ง/นาที จาก "IP เดียว"
      แต่เพดานตั้งไว้ 120/นาที → ทุกคนโดน 429 พร้อมกันภายในวินาทีแรก
      (คอมเมนต์เตือนเรื่องนี้อยู่บนหัวไฟล์นี้มาตลอด แต่ scope "live" ไม่ได้ทำตาม)

    วิธีแก้: ถ้ามี token ให้นับต่อ user (แต่ละเครื่องมี bucket ของตัวเอง)
    ไม่มี token ค่อยตกไปนับต่อ IP ด้วยเพดานที่สูงกว่ามาก

    ตั้งใจ "ไม่" เช็ค denylist ตรงนี้ — เป็นแค่การเลือก bucket ไม่ใช่การ auth
    ประหยัด Redis ไป 1 รอบบน endpoint ที่โดนหนักที่สุดของทั้งระบบ
    """
    if uid := _user_id_from_header(request):
        await check(scope, f"u:{uid}")
        return
    await check(f"{scope}_anon", f"ip:{client_ip(request)}")


def _user_id_from_header(request: Request) -> str | None:
    """อ่าน sub จาก JWT โดยไม่แตะ Redis — decode เป็น CPU ล้วน ราคาถูก"""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        from app.core.security import decode_access_token
        return decode_access_token(auth[7:]).get("sub")
    except Exception:
        return None


def client_ip(request: Request) -> str:
    """ดึง IP จริงจากหลัง Cloudflare + Nginx

    ลำดับสำคัญ: CF-Connecting-IP เชื่อถือได้ที่สุดเมื่ออยู่หลัง Cloudflare
    ⚠️ header พวกนี้ปลอมได้ถ้าไม่ได้อยู่หลัง proxy จริง — ต้องมั่นใจว่า
       Nginx ตั้ง real_ip_header และ set_real_ip_from เป็น Cloudflare IP ranges
    """
    for header in ("cf-connecting-ip", "x-real-ip"):
        if v := request.headers.get(header):
            return v.strip()
    if xff := request.headers.get("x-forwarded-for"):
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


async def idempotent_get(scope: str, key: str) -> str | None:
    """ดึงผลลัพธ์ที่เคยตอบไปแล้วสำหรับ Idempotency-Key นี้"""
    return await get_redis().get(f"idem:{scope}:{key}")


async def idempotent_set(scope: str, key: str, value: str, ttl: int = 86400) -> None:
    await get_redis().set(f"idem:{scope}:{key}", value, ex=ttl)
