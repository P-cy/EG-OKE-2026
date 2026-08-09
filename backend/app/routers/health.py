"""Health / readiness / metrics

★ healthz กับ readyz ต้องแยกกัน:
  · healthz  = process ยังอยู่ไหม → Docker ใช้ตัดสินว่าจะ restart ไหม
  · readyz   = พร้อมรับ traffic ไหม → Nginx ใช้ตัดสินว่าจะส่ง request มาไหม

ถ้ารวมเป็นตัวเดียว: Mongo ช้าชั่วคราว → Docker restart container ทิ้ง → แย่ลงไปอีก
"""
import ipaddress
import os

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core import db, redis_client
from app.core.config import settings

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz():
    """liveness — คืน 200 เสมอถ้า process ยังตอบได้"""
    return {"status": "alive"}


@router.get("/readyz")
async def readyz(response: Response):
    """readiness — เช็ค dependency จริง"""
    mongo_ok = await db.ping()
    redis_ok = await redis_client.ping()

    # Redis คือ hard dependency (vote/dedupe/rate limit ใช้หมด)
    # Mongo ล่มยังทำงานใน degraded mode ได้ → ไม่ถือว่า not ready
    ready = redis_ok
    if not ready:
        response.status_code = 503

    return {
        "status": "ready" if ready else "not_ready",
        "checks": {"mongo": mongo_ok, "redis": redis_ok},
        "degraded": redis_ok and not mongo_ok,
    }


@router.get("/version")
async def version():
    return {
        "version": os.getenv("APP_VERSION", "dev"),
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "built_at": os.getenv("BUILD_TIME", "unknown"),
        "env": settings.ENV,
    }


@router.get("/metrics")
async def metrics(request: Request):
    """Prometheus — จำกัด IP ภายในเท่านั้น

    metrics เปิดเผยข้อมูลระบบเยอะ (จำนวนผู้ใช้, endpoint ที่มี, error rate)
    ห้ามเปิดสาธารณะ
    """
    client = request.client.host if request.client else ""
    if not _ip_allowed(client):
        return Response(status_code=403)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _ip_allowed(ip: str) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in settings.METRICS_ALLOWED_IPS.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False
