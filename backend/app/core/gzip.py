"""GZip แบบไม่บีบอัด SSE

Starlette GZipMiddleware บีบอัดทุก response → SSE (text/event-stream) ถูกบัฟเฟอร์รวมเป็นก้อน
ทำให้ push ไม่สด (client ได้ข้อมูลช้า). ตัวนี้ skip path ที่เป็น SSE ให้ผ่านดิบๆ.

ใช้: app.add_middleware ทำไม่ได้ (ต้องเป็น ASGI middleware class) → ใช้แบบ wrap เองใน main.py
"""
from starlette.middleware.gzip import GZipMiddleware

# path ที่เป็น SSE — ข้าม gzip
SSE_PATHS = ("/v1/me/stream",)


class GZipExceptSSEMiddleware:
    """ASGI middleware: gzip ทุกอย่าง ยกเว้น SSE path (ผ่านดิบ)"""

    def __init__(self, app, minimum_size: int = 500):
        self.inner = app
        self.gz = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "") in SSE_PATHS:
            # SSE → เรียก app ดิบ (ไม่ gzip)
            await self.inner(scope, receive, send)
            return
        # อื่น → gzip ปกติ
        await self.gz(scope, receive, send)
