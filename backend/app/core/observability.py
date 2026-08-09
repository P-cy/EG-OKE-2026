"""Structured logging + Prometheus metrics + request_id middleware"""
import logging
import time

import structlog
from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from ulid import ULID

from app.core.config import settings

# ── Metrics ────────────────────────────────────────────────────────────
REQUESTS = Counter(
    "egoke_http_requests_total", "HTTP requests", ["route", "method", "status"]
)
DURATION = Histogram(
    "egoke_http_duration_seconds",
    "HTTP request duration",
    ["route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
VOTES = Counter("egoke_votes_accepted_total", "Votes accepted", ["round_key"])
CHECKINS = Counter("egoke_checkins_total", "Check-in scans", ["result", "gate"])
STREAM_LAG = Gauge("egoke_vote_stream_lag", "Pending messages in vote stream")
WS_CONNS = Gauge("egoke_ws_connections_active", "Active WebSocket connections")
COINS_DRIFT = Gauge("egoke_coins_ledger_drift", "Users whose balance != ledger sum")


def setup_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # JSON ใน prod เพื่อให้ Loki parse ได้, console ตอน dev เพื่อให้คนอ่านได้
            structlog.processors.JSONRenderer()
            if settings.is_prod
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """ใส่ request_id ทุก request + วัดเวลา + log

    request_id ทำให้ staff หน้างานบอกเลขมา แล้วเราเปิด log เจอทันที
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(ULID())
        request.state.request_id = rid
        structlog.contextvars.bind_contextvars(request_id=rid)

        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            elapsed = time.perf_counter() - start
            # ใช้ route pattern ไม่ใช่ path จริง — ไม่งั้น metric cardinality ระเบิด
            # (/users/123 กับ /users/456 ต้องนับเป็น route เดียวกัน)
            route = request.scope.get("route")
            route_name = getattr(route, "path", request.url.path)

            DURATION.labels(route=route_name).observe(elapsed)
            REQUESTS.labels(
                route=route_name, method=request.method, status=str(status)
            ).inc()

            if elapsed > 1.0 or status >= 500:
                log.warning(
                    "slow_or_failed_request",
                    route=route_name,
                    method=request.method,
                    status=status,
                    duration_ms=round(elapsed * 1000, 1),
                    user_id=getattr(request.state, "user_id", None),
                )
            structlog.contextvars.clear_contextvars()
