"""audit log — บันทึกทุก action ของคนที่มีสิทธิ์พิเศษ

★ แยกออกมาจาก routers/admin.py เพราะ staff ก็ทำ action ที่ต้องตามรอยได้แล้ว
  (เช็คชื่อด้วยมือ) ถ้าปล่อยให้ฟังก์ชันนี้อยู่ใน admin.py แล้ว router อื่นไป import
  จะกลายเป็น router import router ซึ่งพันกันเร็วมาก
"""
from datetime import datetime, timezone

from fastapi import Request

from app.core.db import Col
from app.core.deps import CurrentUser
from app.core.ratelimit import client_ip
from app.core.security import hash_ip


async def audit(
    request: Request, actor: CurrentUser, action: str,
    target_type: str, target_id, before=None, after=None,
) -> None:
    """เรียกทุกครั้งที่ admin/staff ทำอะไร — ไม่มีข้อยกเว้น

    นี่คือสิ่งเดียวที่กัน insider threat ได้จริง
    """
    await Col.audit_logs().insert_one({
        "actor_id": actor.oid,
        "action": action,
        "target": {"type": target_type, "id": target_id},
        "before": before,
        "after": after,
        "ip_hash": hash_ip(client_ip(request)),
        "user_agent": request.headers.get("user-agent", "")[:200],
        "created_at": datetime.now(timezone.utc),
    })
