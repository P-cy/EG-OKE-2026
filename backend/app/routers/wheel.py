"""Wheel — server-authoritative, provably fair

ลำดับที่ห้ามสลับ:
  1. หักเหรียญก่อน  (ถ้าไม่พอ จบ)
  2. คำนวณผลด้วย HMAC
  3. ตัด stock แบบ atomic (ถ้าหมด → ตกเป็น "ไม่ถูกรางวัล")
  4. บันทึก spin + ให้รางวัล

วงล้อหมุนในมือถือคนเล่นเท่านั้น — ไม่มีจอใหญ่ ไม่มี broadcast
"""
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pymongo.errors import DuplicateKeyError

from app.core import ratelimit
from app.core.db import Col
from app.core.deps import CurrentUserDep, require_feature, require_writable
from app.core.errors import AppError, conflict, forbidden, not_found
from app.models.schemas import SpinIn, SpinOut
from app.services import coins, wheel_engine

router = APIRouter(prefix="/wheel", tags=["wheel"])


@router.get("/{wheel_key}")
async def get_wheel(wheel_key: str, user: CurrentUserDep):
    w = await Col.wheel_configs().find_one({"wheel_key": wheel_key})
    if not w:
        raise not_found("วงล้อ")

    used = await Col.wheel_spins().count_documents(
        {"user_id": user.oid, "wheel_key": wheel_key}
    )
    balance = await coins.balance_of(user.oid)

    return {
        "wheel_key": wheel_key,
        "title": w.get("title", ""),
        "cost_coins": w.get("cost_coins", 0),
        "status": w.get("status", "draft"),
        # ★ ไม่ส่ง weight ให้ client — ไม่งั้นคนคำนวณ EV แล้วบ่นว่าโกง
        "segments": [
            {
                "id": s["id"],
                "label": s["label"],
                "prize_type": s.get("prize_type", "none"),
                "sold_out": s.get("remaining") is not None and s["remaining"] <= 0,
            }
            for s in w.get("segments", [])
        ],
        "commit_hash": w.get("commit_hash"),   # ★ พิสูจน์ว่าไม่ล็อกผล
        "max_spins_per_user": w.get("max_spins_per_user", 1),
        "my_spins_used": used,
        "my_spins_left": max(0, w.get("max_spins_per_user", 1) - used),
        "my_coins": balance,
    }


@router.post(
    "/{wheel_key}/spin",
    response_model=SpinOut,
    dependencies=[Depends(require_feature("wheel", "วงล้อ")), Depends(require_writable)],
)
async def spin(
    wheel_key: str,
    body: SpinIn,
    user: CurrentUserDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    await ratelimit.check("spin", user.id)

    idem = idempotency_key or f"spin:{user.id}:{wheel_key}:{body.nonce}"
    if cached := await ratelimit.idempotent_get("spin", idem):
        return SpinOut(**json.loads(cached))

    w = await Col.wheel_configs().find_one({"wheel_key": wheel_key})
    if not w:
        raise not_found("วงล้อ")
    if w.get("status") != "open":
        raise conflict("WHEEL_CLOSED", "วงล้อนี้ยังไม่เปิดหรือปิดแล้ว")

    used = await Col.wheel_spins().count_documents({"user_id": user.oid, "wheel_key": wheel_key})
    if used >= w.get("max_spins_per_user", 1):
        raise forbidden("SPIN_LIMIT_REACHED", "คุณหมุนครบจำนวนครั้งที่กำหนดแล้ว")

    segments = w.get("segments", [])
    cost = int(w.get("cost_coins", 0))

    # ── 1. หักเหรียญก่อน (atomic — กันกดรัวแล้วยอดติดลบ) ──
    if cost > 0:
        spent = await coins.spend(
            user_id=user.oid, amount=cost, reason="wheel_cost",
            idempotency_key=f"{idem}:cost",
            ref={"type": "wheel", "id": wheel_key},
        )
        if spent.insufficient:
            raise AppError(
                402, "INSUFFICIENT_COINS",
                f"เหรียญไม่พอ ต้องมีอย่างน้อย {cost} เหรียญ",
                "Insufficient coins",
                details={"required": cost, "balance": spent.balance},
            )

    # ── 2. คำนวณผลที่ server (HMAC — ทำซ้ำได้ พิสูจน์ได้) ──
    idx, segment, digest = wheel_engine.compute_result(
        segments, body.client_seed, body.nonce, w.get("server_seed")
    )

    # ── 3. ตัด stock แบบ atomic ──
    if segment.get("remaining") is not None:
        ok = await Col.wheel_configs().update_one(
            {
                "wheel_key": wheel_key,
                "segments": {"$elemMatch": {"id": segment["id"], "remaining": {"$gt": 0}}},
            },
            {"$inc": {"segments.$.remaining": -1}},
        )
        if ok.modified_count == 0:
            # ของหมดพอดี → ตกเป็น "ไม่ถูกรางวัล" (ไม่คืนเงิน ตามกติกาที่ประกาศ)
            idx, segment = wheel_engine.fallback_segment(segments)

    # ── 4. บันทึก + ให้รางวัล ──
    won = int(segment.get("coins", 0)) if segment.get("prize_type") == "coins" else 0
    try:
        res = await Col.wheel_spins().insert_one({
            "idempotency_key": idem,
            "wheel_key": wheel_key,
            "user_id": user.oid,
            "nonce": body.nonce,
            "client_seed": body.client_seed,
            "result_segment_id": segment["id"],
            "result_hmac": digest,
            "coins_spent": cost,
            "coins_won": won,
            "prize_claimed": False,
            "spun_at": datetime.now(timezone.utc),
            "schema_version": 1,
        })
    except DuplicateKeyError:
        # ★ ต้องคืนเหรียญ — เราหักไปแล้วตั้งแต่ขั้นที่ 1 แต่การหมุนไม่ถูกบันทึก
        #   ของเดิม raise เฉยๆ = ผู้ใช้เสียเหรียญฟรี
        #   (unique index (user_id, wheel_key, nonce) — ชนได้จริงตอนกดสองแท็บพร้อมกัน)
        await _refund(user.oid, cost, f"{idem}:refund", wheel_key)
        raise conflict("NONCE_ALREADY_USED", "การหมุนครั้งนี้ถูกบันทึกไปแล้ว เหรียญถูกคืนแล้ว")

    # ★ กันยิงพร้อมกันหลาย request แล้วหมุนเกินโควตา
    #   ด่านที่ 1 (บรรทัดบน) เป็น check-then-act — สองคำขอพร้อมกันผ่านทั้งคู่ได้
    #   ตรงนี้นับ "หลังจอง" แล้ว ถ้าเกินก็ถอยคืนทั้งใบ (ลบ spin + คืนเหรียญ)
    total = await Col.wheel_spins().count_documents({"user_id": user.oid, "wheel_key": wheel_key})
    if total > w.get("max_spins_per_user", 1):
        await Col.wheel_spins().delete_one({"_id": res.inserted_id})
        if segment.get("remaining") is not None:
            await Col.wheel_configs().update_one(
                {"wheel_key": wheel_key, "segments.id": segment["id"]},
                {"$inc": {"segments.$.remaining": 1}},
            )
        await _refund(user.oid, cost, f"{idem}:refund", wheel_key)
        raise forbidden("SPIN_LIMIT_REACHED", "คุณหมุนครบจำนวนครั้งที่กำหนดแล้ว")

    balance = await coins.balance_of(user.oid)
    if won > 0:
        r = await coins.award(
            user_id=user.oid, amount=won, reason="wheel_prize",
            idempotency_key=f"{idem}:prize",
            ref={"type": "wheel_spin", "id": str(res.inserted_id)},
        )
        balance = r.balance

    out = SpinOut(
        spin_id=str(res.inserted_id),
        result_segment_id=segment["id"],
        segment_index=idx,            # ★ frontend ใช้เลขนี้คำนวณองศา
        label=segment["label"],
        prize_type=segment.get("prize_type", "none"),
        coins_won=won,
        coins_spent=cost,
        coins_balance=balance,
        proof={"nonce": body.nonce, "client_seed": body.client_seed, "hmac": digest},
    )
    await ratelimit.idempotent_set("spin", idem, out.model_dump_json())
    # ไม่มี broadcast ไปจอแล้ว — วงล้อหมุนอยู่ในมือถือคนเล่นเท่านั้น
    return out


async def _refund(user_oid, cost: int, key: str, wheel_key: str) -> None:
    """คืนค่าหมุนเมื่อการหมุนไม่ถูกบันทึก — idempotent ผูกกับ key ของ request นั้น"""
    if cost <= 0:
        return
    await coins.award(
        user_id=user_oid, amount=cost, reason="wheel_refund",
        idempotency_key=key, ref={"type": "wheel", "id": wheel_key},
        note="คืนค่าหมุนที่ไม่สำเร็จ",
    )


@router.get("/{wheel_key}/verify")
async def verify_wheel(wheel_key: str):
    """เปิดหลังจบงาน — เปิดเผย server_seed ให้ทุกคนตรวจสอบเองได้"""
    w = await Col.wheel_configs().find_one({"wheel_key": wheel_key})
    if not w:
        raise not_found("วงล้อ")
    if w.get("status") != "closed":
        raise forbidden("WHEEL_NOT_CLOSED", "จะเปิดเผยข้อมูลตรวจสอบหลังปิดวงล้อแล้ว")

    return {
        "wheel_key": wheel_key,
        "commit_hash": w.get("commit_hash"),
        "server_seed": w.get("server_seed"),
        "segments": [
            {"id": s["id"], "label": s["label"], "weight": s.get("weight")}
            for s in w.get("segments", [])
        ],
        "algorithm": "index = int(HMAC_SHA256(server_seed, f'{client_seed}:{nonce}')[:8], 16) "
                     "% sum(weights) → หา segment จาก cumulative weight",
        "note": "ตรวจสอบว่า sha256(server_seed) ตรงกับ commit_hash ที่ประกาศไว้ก่อนงาน",
    }
