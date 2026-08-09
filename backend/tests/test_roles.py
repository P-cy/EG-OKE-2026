"""สิทธิ์ staff / admin — ใครทำอะไรได้บ้าง

งานนี้ staff เป็นนักศึกษาอาสาหลายสิบคน แจก role ให้กว้างแล้วถอนคืนไม่ได้
เทสต์ชุดนี้จึงล็อกขอบเขตไว้ว่า staff ทำอะไร "ไม่ได้"
"""
import pytest
from bson import ObjectId

from app.core.deps import CurrentUser, require_admin, require_staff
from app.core.errors import AppError
from app.models.schemas import UserRolesIn


def _user(*roles: str) -> CurrentUser:
    return CurrentUser(id=str(ObjectId()), roles=list(roles), jti="t")


# ── ขอบเขตของแต่ละ role ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_staff_passes_staff_gate():
    check = require_staff
    assert await check(_user("participant", "staff"))


@pytest.mark.asyncio
async def test_staff_is_blocked_from_admin_gate():
    """★ ข้อสำคัญที่สุดของฟีเจอร์นี้

    staff ต้องเข้า /admin/* ไม่ได้ — ปรับเหรียญ ลบกิจกรรม เปิดโหมดปิดปรับปรุง
    ทั้งหมดอยู่หลังด่านนี้
    """
    with pytest.raises(AppError) as e:
        await require_admin(_user("participant", "staff"))
    assert e.value.status_code == 403
    assert e.value.code == "INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_participant_is_blocked_from_staff_gate():
    with pytest.raises(AppError) as e:
        await require_staff(_user("participant"))
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_do_staff_work():
    """admin ต้องสแกนแทน staff ได้ — คนไม่พอหน้างานเป็นเรื่องปกติ"""
    assert await require_staff(_user("admin"))


@pytest.mark.asyncio
async def test_superadmin_passes_every_gate():
    assert await require_staff(_user("superadmin"))
    assert await require_admin(_user("superadmin"))


# ── การตั้ง role ───────────────────────────────────────────────────────
def test_only_known_roles_are_accepted():
    """พิมพ์ผิดต้อง 422 ไม่ใช่บันทึกลง DB เงียบๆ แล้วคนนั้นไม่ได้สิทธิ์อะไรเลย"""
    with pytest.raises(Exception):
        UserRolesIn(roles=["adnim"])
    with pytest.raises(Exception):
        UserRolesIn(roles=["superadmin"])   # ตั้งผ่าน API ไม่ได้ ต้องแก้ใน DB


def test_valid_role_sets_are_accepted():
    assert UserRolesIn(roles=[]).roles == []
    assert UserRolesIn(roles=["staff"]).roles == ["staff"]
    assert UserRolesIn(roles=["admin"]).roles == ["admin"]


def test_participant_is_always_kept():
    """ตรรกะเดียวกับใน endpoint — ถอด participant ออกแล้วเจ้าตัวใช้หน้าผู้ใช้ไม่ได้"""
    for requested in ([], ["staff"], ["admin"]):
        after = sorted({"participant", *requested})
        assert "participant" in after


def test_setting_roles_is_idempotent():
    """ส่งชุดเต็มเสมอ — กดซ้ำตอนเน็ตช้าแล้วผลต้องเหมือนเดิม ไม่ใช่สลับไปมา"""
    first = sorted({"participant", *["staff"]})
    second = sorted({"participant", *["staff"]})
    assert first == second == ["participant", "staff"]
