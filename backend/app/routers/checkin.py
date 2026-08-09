"""Check-in — สแกน QR หน้างาน

ต้อง: idempotent · เร็ว (<200ms) · รองรับ offline queue · บอกผลชัดเจนให้ staff

★ บัตร 1 ใบต่อ user ทั้งงาน → สแกนซ้ำทุกวันได้ → dedupe เป็น "รายวัน"
  - Redis `ci:{ticket_id}:d{day}` (TTL 4 วัน) เป็นด่านจริง (เร็ว กัน race)
  - Mongo `$addToSet checked_in_days` เงื่อน `checked_in_days != day` เป็นด่านสำรอง
  - coin award idempotent รายวัน: `checkin:{ticket_code}:d{day}` → มา 3 วันได้ 3×

★ ทางเข้า 3 ทาง (resolve_ticket) — หน้างานจริงกล้องอ่านไม่ติดบ่อย ต้องมีทางถอย
  1. QR payload เต็ม (กล้อง/สแกนเนอร์)
  2. รหัสบัตร EGOKE26-XXXXXXXX (staff พิมพ์จากจอผู้เข้างาน)
  3. รหัสนักศึกษา 7 หลัก (มือถือแบตหมด/เปิดบัตรไม่ได้)
  ทาง 2/3 ข้าม HMAC ได้เพราะ endpoint นี้ require_staff อยู่แล้ว — คนกดคือเจ้าหน้าที่
"""
import json
import re
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pymongo.errors import DuplicateKeyError

from app.core import ratelimit
from app.core.config import settings
from app.core.db import Col
from app.core.deps import CurrentUser, ConfigDep, require_feature, require_staff
from app.core.observability import CHECKINS, log
from app.core.redis_client import K, get_redis
from app.core.security import QR_PREFIX, totp_verify, verify_qr_payload
from app.models.schemas import CheckinBatchIn, CheckinIn, CheckinOut
from app.realtime.notify_manager import NOTIFY_CHANNEL
from app.services import coins

router = APIRouter(tags=["checkin"])


@router.post(
    "/checkin",
    response_model=CheckinOut,
    dependencies=[Depends(require_feature("checkin", "เช็คอิน"))],
)
async def checkin(
    body: CheckinIn,
    staff: Annotated[CurrentUser, Depends(require_staff)],
    cfg: ConfigDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    await ratelimit.check("checkin", body.device_id)
    return await _process(body, staff, idempotency_key)


@router.post(
    "/checkin/batch",
    dependencies=[Depends(require_feature("checkin", "เช็คอิน"))],
)
async def checkin_batch(
    body: CheckinBatchIn,
    staff: Annotated[CurrentUser, Depends(require_staff)],
    idempotency_keys: Annotated[str | None, Header(alias="Idempotency-Keys")] = None,
):
    """รับ queue ที่ค้างจาก scanner ตอน offline

    ★ ห้ามล้มทั้ง batch ถ้ารายการเดียวพัง — ประมวลผลทีละตัวและคืนผลรายตัว
    """
    keys = (idempotency_keys or "").split(",") if idempotency_keys else []
    results = []
    for i, item in enumerate(body.items):
        key = keys[i].strip() if i < len(keys) else None
        try:
            out = await _process(item, staff, key, offline=True)
            results.append({"idempotency_key": key, **out.model_dump(mode="json")})
        except Exception as e:
            log.warning("batch_checkin_item_failed", error=str(e), index=i)
            results.append({"idempotency_key": key, "result": "error", "message": str(e)})
    return {"results": results, "processed": len(results)}


TICKET_CODE_RE = re.compile(r"^EGOKE26-[0-9A-F]{4,16}$")
STUDENT_ID_RE = re.compile(r"^\d{7}$")


def classify_code(raw: str) -> tuple[str, str]:
    """ตัดสินว่าสิ่งที่ staff สแกน/พิมพ์มาเป็นอะไร — ฟังก์ชันบริสุทธิ์ (ไม่แตะ DB)

    คืน (kind, normalized)
      kind: "qr" | "ticket_code" | "student_id" | "unknown"

    แยกออกมาเพื่อ unit test ได้โดยไม่ต้องมี Mongo — ตรงนี้คือจุดที่พลาดแล้ว
    คนหน้าประตูเข้าไม่ได้ (เคยพังมาแล้วตอน min_length=20 ทำให้รหัสบัตรโดน 422)
    """
    code = raw.strip()
    if code.startswith(f"{QR_PREFIX}:"):
        return "qr", code
    upper = code.upper()
    if TICKET_CODE_RE.match(upper):
        return "ticket_code", upper
    if STUDENT_ID_RE.match(code):
        return "student_id", code
    return "unknown", code


async def resolve_ticket(raw: str) -> tuple[dict | None, str, str, str | None]:
    """แปลงสิ่งที่ staff สแกน/พิมพ์ → ticket

    คืน (ticket, matched_by, reason, ticket_code)
    reason: "ok" | "malformed" | "invalid_sig" | "wrong_version" | "not_found" | "no_ticket"
    """
    kind, code = classify_code(raw)

    # ── 1. QR payload เต็ม → ตรวจ HMAC ก่อนแตะ DB (เร็ว + ปฏิเสธของปลอมทันที) ──
    if kind == "qr":
        valid, ticket_code, reason = verify_qr_payload(code)
        if not valid:
            return None, "qr", reason, ticket_code
        ticket = await Col.tickets().find_one({"ticket_code": ticket_code})
        return ticket, "qr", ("ok" if ticket else "not_found"), ticket_code

    # ── 2. รหัสบัตรล้วน (staff พิมพ์จากจอผู้เข้างาน) ──
    if kind == "ticket_code":
        ticket = await Col.tickets().find_one({"ticket_code": code})
        return ticket, "ticket_code", ("ok" if ticket else "not_found"), code

    # ── 3. รหัสนักศึกษา 7 หลัก → หา user → หาบัตรของ user ──
    if kind == "student_id":
        user = await Col.users().find_one({"student_id": code}, {"_id": 1})
        if not user:
            return None, "student_id", "not_found", None
        ticket = await Col.tickets().find_one({"user_id": user["_id"]})
        # เจอคนแต่ไม่มีบัตร = ยังไม่ได้ทำ onboarding — ข้อความต้องต่างจาก "ไม่พบ"
        return ticket, "student_id", ("ok" if ticket else "no_ticket"), None

    return None, "unknown", "malformed", None


# ข้อความไทยที่ staff อ่านแล้วรู้ว่าต้องทำอะไรต่อ — ห้ามโชว์ code ดิบให้คนหน้างาน
REASON_MESSAGE = {
    "malformed": "อ่านรหัสไม่ออก — ให้ผู้เข้างานเปิดหน้าบัตร แล้วสแกนใหม่ หรือพิมพ์รหัสนักศึกษา 7 หลัก",
    "invalid_sig": "QR ไม่ถูกต้อง (ลายเซ็นไม่ตรง) — อาจเป็นบัตรปลอมหรือ QR จากงานอื่น",
    "wrong_version": "QR เป็นเวอร์ชันเก่า — ให้ผู้เข้างานรีเฟรชหน้าบัตรแล้วสแกนใหม่",
    "not_found": "ไม่พบบัตรนี้ในระบบ — ตรวจรหัสอีกครั้ง หรือค้นจากรายชื่อ",
    "no_ticket": "ยังไม่มีบัตร — ให้ผู้เข้างานล็อกอินและตั้งค่าโปรไฟล์ให้เสร็จก่อน",
    "revoked": "บัตรถูกยกเลิก — ห้ามให้เข้า ติดต่อหัวหน้าทีม",
    "rotating_code_mismatch": "รหัสหมุนไม่ตรง — ให้ผู้เข้างานเปิดหน้าบัตรจริง (ไม่ใช่ภาพแคปหน้าจอ)",
}


async def _process(
    body: CheckinIn,
    staff: CurrentUser,
    idem_key: str | None,
    offline: bool = False,
) -> CheckinOut:
    """ตรวจของที่สแกนมา (QR / รหัสบัตร / รหัสนักศึกษา) แล้วส่งต่อ checkin_core"""
    now = datetime.now(timezone.utc)

    # ── idempotency: ยิงซ้ำต้องได้ผลเดิม ──
    if idem_key:
        if cached := await ratelimit.idempotent_get("checkin", idem_key):
            return CheckinOut(**json.loads(cached))

    ticket, matched_by, reason, ticket_code = await resolve_ticket(body.payload)

    if ticket is None:
        # malformed/invalid_sig → invalid_sig, ไม่เจอ → not_found, ไม่มีบัตร → no_ticket
        result = {
            "malformed": "invalid_sig", "invalid_sig": "invalid_sig",
            "wrong_version": "invalid_sig", "no_ticket": "no_ticket",
        }.get(reason, "not_found")
        CHECKINS.labels(result=reason, gate=body.gate).inc()
        await _log_scan(None, ticket_code, body.event_day, body.gate, body.device_id,
                        staff, reason, now, offline, idem_key, source=matched_by)
        return CheckinOut(
            result=result, event_day=body.event_day, matched_by=matched_by,
            message=REASON_MESSAGE.get(reason, "สแกนไม่สำเร็จ"),
        )

    ticket_code = ticket["ticket_code"]

    if ticket["status"] == "revoked":
        CHECKINS.labels(result="revoked", gate=body.gate).inc()
        await _log_scan(ticket["_id"], ticket_code, body.event_day, body.gate, body.device_id,
                        staff, "revoked", now, offline, idem_key, source=matched_by)
        return CheckinOut(
            result="revoked", event_day=body.event_day, matched_by=matched_by,
            message=REASON_MESSAGE["revoked"],
        )

    # ── rotating code (anti-screenshot) — เฉพาะทาง QR เท่านั้น ──
    #   ทาง ticket_code/student_id ไม่มีรหัสหมุนให้ตรวจอยู่แล้ว (staff เป็นคนยืนยันตัวตน)
    if settings.STRICT_QR_MODE and matched_by == "qr":
        if not body.rotating_code or not totp_verify(ticket_code, body.rotating_code):
            CHECKINS.labels(result="rotating_code_mismatch", gate=body.gate).inc()
            await _log_scan(ticket["_id"], ticket_code, body.event_day, body.gate, body.device_id,
                            staff, "rotating_code_mismatch", now, offline, idem_key, source=matched_by)
            return CheckinOut(
                result="rotating_code_mismatch", event_day=body.event_day, matched_by=matched_by,
                message=REASON_MESSAGE["rotating_code_mismatch"],
            )

    # ── ส่งต่อ core (dedupe + coin + stats + log) ──
    out = await checkin_core(
        ticket=ticket,
        event_day=body.event_day,
        staff=staff,
        gate=body.gate,
        source=matched_by,
        device_id=body.device_id,
        scanned_at=body.scanned_at,
        idem_key=idem_key,
        offline=offline,
        now=now,
    )
    out.matched_by = matched_by
    if idem_key:
        await ratelimit.idempotent_set("checkin", idem_key, out.model_dump_json())
    return out


async def checkin_core(
    *,
    ticket: dict,
    event_day: int,
    staff: CurrentUser,
    gate: str,
    source: str,            # "qr" | "manual"
    device_id: str | None,
    scanned_at: datetime | None,
    idem_key: str | None,
    offline: bool = False,
    now: datetime | None = None,
) -> CheckinOut:
    """แชร์ระหว่าง QR path (_process) และ admin manual path

    ทำ: dedupe รายวัน → อัปเดต ticket → ให้ coin → stats → log
    ไม่ทำ: HMAC/TOTP (ทำเฉพาะ QR path ก่อนเข้าในนี้)
    """
    now = now or datetime.now(timezone.utc)
    r = get_redis()
    ticket_id = ticket["_id"]
    ticket_code = ticket["ticket_code"]

    user = await Col.users().find_one(
        {"_id": ticket["user_id"]},
        {"display_name": 1, "full_name": 1, "avatar_url": 1, "student_id": 1},
    )
    user_public = {
        "display_name": (user or {}).get("display_name", "?"),
        # ★ staff ต้องเห็นชื่อจริงเทียบกับบัตรนักศึกษา — ชื่อเล่นอย่างเดียวยืนยันตัวตนไม่ได้
        "full_name": (user or {}).get("full_name"),
        "avatar_url": (user or {}).get("avatar_url"),
        "student_id": (user or {}).get("student_id"),
    }

    # ── 1. ★ atomic claim รายวัน: SET NX ใน Redis คือด่านจริง ──
    #    บัตรเดียวกันสแกนวันเดียวกันซ้ำ = duplicate; ข้ามวัน = ok
    dedupe_key = K.CHECKIN_DEDUPE_DAY.format(ticket_id=str(ticket_id), day=event_day)
    claimed = await r.set(dedupe_key, now.isoformat(), nx=True, ex=60 * 60 * 24 * 4)

    if not claimed:
        CHECKINS.labels(result="duplicate", gate=gate).inc()
        out = CheckinOut(
            result="duplicate",
            event_day=event_day,
            message=f"เช็คอินวันที่ {event_day} ไปแล้ว — ผ่านได้เลย ไม่ต้องสแกนซ้ำ",
            user=user_public,
            ticket=_ticket_public(ticket, event_day),
            checked_in_at=ticket.get("last_checked_in_at"),
            checked_in_gate=ticket.get("last_checked_in_gate"),
        )
        await _log_scan(ticket_id, ticket_code, event_day, gate, device_id,
                        staff, "duplicate", now, offline, idem_key, source=source)
        return out

    # ── 2. อัปเดต ticket (ด่านสำรอง: $addToSet รายวัน กันซ้ำถ้า Redis เคย flush) ──
    updated = await Col.tickets().find_one_and_update(
        {"_id": ticket_id, "checked_in_days": {"$ne": event_day}},
        {
            "$addToSet": {"checked_in_days": event_day},
            "$set": {
                "last_checked_in_at": scanned_at or now,
                "last_checked_in_by": staff.oid,
                "last_checked_in_gate": gate,
            },
        },
        return_document=True,
    )
    if not updated:
        # Redis บอกว่ายังไม่เช็ควันนี้ แต่ Mongo บอกว่าเช็คแล้ว → เชื่อ Mongo
        CHECKINS.labels(result="duplicate", gate=gate).inc()
        out = CheckinOut(
            result="duplicate",
            event_day=event_day,
            message=f"เช็คอินวันที่ {event_day} ไปแล้ว — ผ่านได้เลย ไม่ต้องสแกนซ้ำ",
            user=user_public,
            ticket=_ticket_public(ticket, event_day),
            checked_in_at=ticket.get("last_checked_in_at"),
            checked_in_gate=ticket.get("last_checked_in_gate"),
        )
        await _log_scan(ticket_id, ticket_code, event_day, gate, device_id,
                        staff, "duplicate", now, offline, idem_key, source=source)
        return out

    # ── 3. ให้เหรียญเช็คอินรายวัน (idempotent ด้วย key ที่ผูกกับ ticket+วัน) ──
    awarded = 0
    if settings.CHECKIN_COINS > 0:
        res = await coins.award(
            user_id=ticket["user_id"],
            amount=settings.CHECKIN_COINS,
            reason="checkin",
            idempotency_key=f"checkin:{ticket_code}:d{event_day}",
            ref={"type": "ticket", "id": str(ticket_id), "event_day": event_day},
        )
        awarded = settings.CHECKIN_COINS if res.awarded else 0

    # ── 4. อัปเดตสถิติสำหรับจอ (fire-and-forget, ไม่ critical) ──
    try:
        pipe = r.pipeline()
        pipe.hincrby(K.CHECKIN_STATS, "today", 1)
        pipe.hincrby(K.CHECKIN_STATS, f"day:{event_day}", 1)
        pipe.hincrby(K.CHECKIN_STATS, f"gate:{gate}", 1)
        pipe.zadd(K.CHECKIN_TS, {str(ticket_id): now.timestamp()})
        pipe.zremrangebyscore(K.CHECKIN_TS, 0, now.timestamp() - 300)
        pipe.lpush(K.CHECKIN_RECENT, json.dumps({
            "display_name": user_public["display_name"],
            "avatar_url": user_public["avatar_url"],
            "gate": gate,
            "event_day": event_day,
            "at": now.isoformat(),
        }))
        pipe.ltrim(K.CHECKIN_RECENT, 0, 19)
        pipe.sadd(K.CHECKIN_DAY_SET.format(day=event_day), str(ticket["user_id"]))
        await pipe.execute()
    except Exception:
        log.warning("checkin_stats_failed", ticket_code=ticket_code)

    CHECKINS.labels(result="ok", gate=gate).inc()
    await _log_scan(ticket_id, ticket_code, event_day, gate, device_id,
                    staff, "ok", now, offline, idem_key, source=source)

    # ── 5. best-effort notify: push ไป SSE channel กลาง + persist ไว้ reattach ──
    #   ใช้ channel เดียว `notify:checkin` (ไม่ใช่ channel ราย user) เพราะ singleton
    #   notify_manager route เอง ใช้ Redis connection เดียวตลอด รองรับ 500+ คนเปิดแอป
    #   ถ้า Redis พังตรงนี้ ห้ามทำให้ check-in ล้ม (ทำเสร็จแล้วทั้งโซ่ด้านบน)
    try:
        uid = str(ticket["user_id"])
        notify_payload = json.dumps({
            "uid": uid,                          # ★ singleton ใช้ route ไป queue ของ user
            "type": "checkin_ok",
            "event_day": event_day,
            "coins_awarded": awarded,
            "form_url": settings.ATTENDANCE_FORM_URL,
            "at": now.isoformat(),
        })
        p = r.pipeline()
        p.publish(NOTIFY_CHANNEL, notify_payload)
        p.set(K.NOTIFY_LAST.format(uid=uid), notify_payload, ex=3600)
        await p.execute()
    except Exception:
        log.warning("checkin_notify_failed", ticket_code=ticket_code)

    return CheckinOut(
        result="ok",
        event_day=event_day,
        message=f"เข้างานวันที่ {event_day} เรียบร้อย",
        user=user_public,
        ticket=_ticket_public(updated, event_day),
        coins_awarded=awarded,
        checked_in_at=now,
        checked_in_gate=gate,
    )


def _ticket_public(ticket: dict, event_day: int) -> dict:
    """ข้อมูลบัตรที่ scanner โชว์ให้ staff เห็น — สำคัญคือ "เข้าไปแล้ววันไหนบ้าง" """
    return {
        "ticket_code": ticket.get("ticket_code"),
        "tier": ticket.get("tier", "general"),
        "event_day": event_day,
        "checked_in_days": sorted(ticket.get("checked_in_days", [])),
    }


async def _log_scan(
    ticket_id, ticket_code, event_day, gate, device_id,
    staff, result, now, offline, idem_key, *, source: str = "qr",
):
    """audit log ทุกครั้งที่สแกน รวมถึงครั้งที่ถูกปฏิเสธ

    สำคัญมาก: ตอนมีคนบ่นว่า "ผมสแกนแล้ว" เราต้องพิสูจน์ได้
    """
    try:
        await Col.checkins().insert_one({
            "idempotency_key": idem_key or f"auto:{ticket_code}:{now.timestamp()}",
            "ticket_id": ticket_id,
            "ticket_code": ticket_code,
            "event_day": event_day,
            "source": source,
            "result": result,
            "gate": gate,
            "device_id": device_id,
            "staff_id": staff.oid,
            "scanned_at": now,
            "received_at": now,
            "offline_queued": offline,
            "schema_version": 2,
        })
    except DuplicateKeyError:
        pass  # ยิงซ้ำ — ปกติ
    except Exception:
        log.warning("checkin_audit_failed", ticket_code=ticket_code)
