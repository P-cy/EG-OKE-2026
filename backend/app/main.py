"""FastAPI REST API — โปรเซสหลัก

แยกจาก ws_main.py เพราะ WebSocket ถือ connection ยาว
ถ้ารวมกัน restart api ทีเดียวจอทุกตัวหลุดพร้อมกัน
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.core import db, redis_client
from app.core.config import settings
from app.core.gzip import GZipExceptSSEMiddleware
from app.core.errors import (
    AppError, app_error_handler, http_error_handler, unhandled_error_handler,
    validation_error_handler,
)
from app.core.observability import ObservabilityMiddleware, log, setup_logging
from app.services.profile import REQUIRED_FIELDS
from app.routers import (
    admin, auth, avatars, checkin, exports, health, ig, live, me, quests, staff,
    votes, wheel,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings.validate_production()   # ★ fail fast ถ้าตั้งค่า prod ไม่ปลอดภัย

    mongo_ok = await db.ping()
    redis_ok = await redis_client.ping()
    log.info("api_starting", env=settings.ENV, mongo=mongo_ok, redis=redis_ok)

    # ★ พิมพ์นโยบายที่ "มีผลจริง" ตอนบูต ไม่ใช่ค่าที่เขียนไว้ในไฟล์
    #   เคยเสียเวลาไล่หาสาเหตุมาแล้ว: แก้ .env เป็นค่าว่างแล้ว `docker compose restart`
    #   ซึ่ง **ไม่อ่าน .env ใหม่** — มัน start โปรเซสใหม่ใน container เดิมที่ env ถูกฝัง
    #   ไว้ตั้งแต่ตอนสร้าง ผลคือคนนอกล็อกอินไม่ได้ทั้งที่ไฟล์บอกว่าเปิดรับทุกคนแล้ว
    #   และไม่มีอะไรบอกว่าค่าไหนกำลังทำงานอยู่ (ต้องใช้ `up -d --force-recreate`)
    allowed = settings.allowed_domains
    log.info(
        "auth_policy_effective",
        login_open_to=("ทุก domain" if not allowed else sorted(allowed)),
        profile_required=[label for _k, label in REQUIRED_FIELDS],
        auto_admin_emails=len(settings.admin_emails),
    )
    log.info(
        "grant_limits_effective",
        per_scan=settings.STAFF_GRANT_MAX_PER_SCAN,
        pair_daily=settings.STAFF_GRANT_PER_USER_DAILY,
        receive_daily=settings.USER_GRANT_RECEIVE_DAILY,
        staff_daily=settings.STAFF_GRANT_DAILY_BUDGET,
    )
    if not redis_ok:
        log.error("redis_unreachable_at_startup")   # ไม่ตาย แต่ต้องรู้

    # ★ notify_manager — singleton subscribe channel `notify:checkin` (1 Redis connection)
    #   route ไปยัง queue ราย user สำหรับ SSE push ตอนเช็คอิน (รองรับ 500+ คน)
    from app.realtime.notify_manager import notify_manager
    await notify_manager.start()

    yield

    await notify_manager.stop()
    await redis_client.close_redis()
    await db.close_db()
    log.info("api_stopped")


app = FastAPI(
    title="EG'OKE 2026 API",
    version="1.0.0",
    default_response_class=ORJSONResponse,   # เร็วกว่า json มาตรฐาน ~2-3 เท่า
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
    lifespan=lifespan,
)

# ── Middleware (ลำดับสำคัญ: ตัวที่เพิ่มทีหลังจะทำงานก่อน) ────────────
app.add_middleware(ObservabilityMiddleware)
# ★ gzip ทุกอย่าง ยกเว้น SSE (/me/stream) — ถ้า gzip ด้วยจะบัฟเฟอร์ทำให้ push ไม่สด
app.add_middleware(GZipExceptSSEMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,    # ★ ห้าม ["*"] คู่กับ credentials
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Idempotency-Keys"],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining", "Retry-After"],
    max_age=600,
)

# ── Error handlers ────────────────────────────────────────────────────
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)
# ★ ต้องมาก่อน Exception — ไม่งั้น 422 หลุดเป็น {"detail":[...]} ที่ frontend อ่าน code ไม่ได้
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

# ── Routers ───────────────────────────────────────────────────────────
app.include_router(health.router)                       # ไม่มี prefix (Docker/Nginx เรียกตรง)

V1 = "/v1"
app.include_router(auth.router, prefix=V1)
app.include_router(me.router, prefix=V1)
app.include_router(checkin.router, prefix=V1)
app.include_router(quests.router, prefix=V1)
app.include_router(votes.router, prefix=V1)
app.include_router(votes.rounds_router, prefix=V1)
app.include_router(ig.router, prefix=V1)
app.include_router(wheel.router, prefix=V1)
app.include_router(live.router, prefix=V1)
app.include_router(avatars.router, prefix=V1)
app.include_router(staff.router, prefix=V1)
app.include_router(admin.router, prefix=V1)
app.include_router(exports.router, prefix=V1)   # /admin/export/*.csv


@app.get("/")
async def root():
    return {"service": "EG'OKE 2026 API", "version": "1.0.0", "docs": "/docs"}
