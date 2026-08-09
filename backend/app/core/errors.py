"""Error model กลาง — ทุก error ที่ผู้ใช้เห็นต้องผ่านที่นี่"""
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import ORJSONResponse


class AppError(HTTPException):
    """Error ที่มี code ชัดเจน + ข้อความไทย/อังกฤษ

    ห้ามปล่อย exception ดิบออกไปให้ผู้ใช้เห็น — staff หน้างานต้องอ่านออก
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        message_en: str = "",
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message
        self.message_en = message_en or message
        self.details = details or {}


# ── Catalogue ของ error ทั้งหมด ───────────────────────────────────────
# รวมไว้ที่เดียวเพื่อให้ frontend generate เป็น type ได้ และแปลภาษาได้ครบ

def bad_request(code: str, msg: str, msg_en: str = "") -> AppError:
    return AppError(400, code, msg, msg_en)


def unauthorized(msg: str = "กรุณาเข้าสู่ระบบ") -> AppError:
    return AppError(401, "UNAUTHORIZED", msg, "Authentication required")


def forbidden(code: str, msg: str, msg_en: str = "") -> AppError:
    return AppError(403, code, msg, msg_en)


def not_found(what: str) -> AppError:
    return AppError(404, "NOT_FOUND", f"ไม่พบ{what}", f"{what} not found")


def conflict(code: str, msg: str, details: dict | None = None) -> AppError:
    return AppError(409, code, msg, details=details)


def rate_limited(retry_after: int) -> AppError:
    return AppError(
        429,
        "RATE_LIMITED",
        f"ส่งคำขอถี่เกินไป กรุณารออีก {retry_after} วินาที",
        "Too many requests",
        details={"retry_after": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


def degraded(feature: str) -> AppError:
    return AppError(
        503,
        "FEATURE_DISABLED",
        f"ระบบ{feature}ปิดใช้งานชั่วคราว",
        f"{feature} is temporarily disabled",
    )


async def app_error_handler(request: Request, exc: AppError) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "message_en": exc.message_en,
                "details": exc.details,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


async def http_error_handler(request: Request, exc: HTTPException) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error": {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "message_en": str(exc.detail),
                "details": {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


async def validation_error_handler(request: Request, exc) -> ORJSONResponse:
    """422 จาก pydantic — ★ ต้องมี ไม่งั้น body เป็น {"detail":[...]} ซึ่งไม่ใช่ envelope ของเรา
    แล้ว frontend อ่าน error.code ไม่เจอ → โชว์ "UNKNOWN" ให้ staff เห็นหน้างาน
    """
    errs = getattr(exc, "errors", lambda: [])()
    first = errs[0] if errs else {}
    # loc = ("body", "payload") → "payload"
    field = ".".join(str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path"))
    msg_en = first.get("msg", "invalid input")
    return ORJSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"ข้อมูลไม่ถูกต้อง ({field or 'body'}): {msg_en}",
                "message_en": f"Invalid {field or 'body'}: {msg_en}",
                "details": {"field": field, "errors": len(errs)},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> ORJSONResponse:
    """ตัวสุดท้าย — ห้ามรั่ว stack trace ให้ผู้ใช้เห็น"""
    import structlog

    structlog.get_logger().exception(
        "unhandled_exception",
        path=request.url.path,
        request_id=getattr(request.state, "request_id", None),
    )
    return ORJSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "เกิดข้อผิดพลาดภายในระบบ กรุณาลองใหม่",
                "message_en": "Internal server error",
                "details": {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )
