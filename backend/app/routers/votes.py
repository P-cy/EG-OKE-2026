"""Voting — hot path ที่ต้องรอด 1,500 rps

หัวใจ: POST /votes แตะแค่ Redis (1 Lua script = 1 round-trip)
       ไม่แตะ Mongo เลยใน request path
       → Mongo ล่ม คนก็ยังโหวตได้ ไม่มีโหวตหาย
"""
import json
import time
from datetime import datetime, timezone
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, Header, Request

from app.core import ratelimit
from app.core.config import settings
from app.core.db import Col
from app.core.deps import (
    ConfigDep, CurrentUserDep, OptionalUserDep,
    require_feature, require_writable,
)
from app.core.errors import forbidden, not_found
from app.core.observability import VOTES
from app.core.redis_client import K, get_redis, get_script
from app.core.security import hash_ip
from app.models.schemas import ArtistPublic, VoteIn, VoteOut, VoteRoundPublic

router = APIRouter(prefix="/votes", tags=["voting"])
rounds_router = APIRouter(prefix="/vote-rounds", tags=["voting"])

VOTE_STREAM_MAXLEN = 200_000
DEDUPE_TTL = 60 * 60 * 24 * 5  # 5 วัน (ครอบคลุมงาน 3 วัน + เผื่อ)


@router.post(
    "",
    response_model=VoteOut,
    status_code=202,
    dependencies=[Depends(require_feature("voting", "โหวต")), Depends(require_writable)],
)
async def cast_vote(
    body: VoteIn,
    request: Request,
    user: CurrentUserDep,
    cfg: ConfigDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """บันทึกโหวต

    ⚡ เส้นทาง: rate limit (Redis) → Lua script (Redis) → 202
       ทั้งหมด ~1ms ไม่แตะ Mongo เลย
    """
    await ratelimit.check("vote", user.id)

    # ── ตรวจว่ารอบเปิดอยู่ไหม (cache 3 วิ เพื่อไม่ให้แตะ Mongo ทุก request) ──
    rnd = await _get_round_cached(body.round_key)
    if not rnd:
        raise not_found("รอบโหวต")

    now = datetime.now(timezone.utc)
    if rnd["status"] != "open":
        raise forbidden("VOTE_ROUND_CLOSED", "รอบโหวตนี้ยังไม่เปิดหรือปิดแล้ว")
    if rnd.get("opens_at") and now < _as_utc(rnd["opens_at"]):
        raise forbidden("VOTE_ROUND_NOT_OPEN", "รอบโหวตนี้ยังไม่เปิด")
    if rnd.get("closes_at") and now > _as_utc(rnd["closes_at"]):
        raise forbidden("VOTE_ROUND_CLOSED", "หมดเวลาโหวตแล้ว")
    if body.artist_id not in rnd["candidate_ids"]:
        raise forbidden("ARTIST_NOT_IN_ROUND", "ศิลปินคนนี้ไม่ได้อยู่ในรอบโหวตนี้")

    # ── บังคับเช็คอินก่อนโหวต (ถ้าเปิดกติกานี้) ──
    if settings.REQUIRE_CHECKIN_TO_VOTE:
        from app.services.tickets import has_checked_in

        if not await has_checked_in(user.oid):
            raise forbidden(
                "NOT_CHECKED_IN",
                "ต้องเช็คอินเข้างานก่อนจึงจะโหวตได้",
                "Check-in required before voting",
            )

    # ── ★ หัวใจ: atomic vote ใน Redis round-trip เดียว ──
    script = get_script("vote")
    accepted, artist_id, _total = await script(
        keys=[
            K.VOTE_DEDUPE.format(round=body.round_key, uid=user.id),
            K.VOTE_TALLY.format(round=body.round_key),
            K.VOTE_ZSET.format(round=body.round_key),
            K.VOTE_STREAM,
        ],
        args=[
            user.id,
            body.artist_id,
            body.round_key,
            DEDUPE_TTL,
            int(time.time() * 1000),
            hash_ip(ratelimit.client_ip(request)),
            VOTE_STREAM_MAXLEN,
        ],
    )

    accepted = bool(int(accepted))
    if accepted:
        VOTES.labels(round_key=body.round_key).inc()

    return VoteOut(
        accepted=True,                    # ★ โหวตซ้ำก็ยังคืน accepted=True (idempotent)
        round_key=body.round_key,
        artist_id=artist_id,
        already_voted=not accepted,
        results_visible=bool(rnd.get("results_public")),
    )


@rounds_router.get("", response_model=list[VoteRoundPublic])
async def list_rounds(user: OptionalUserDep):
    """รายการรอบโหวตทั้งหมดที่ผู้ใช้เห็นได้"""
    rounds = await Col.vote_rounds().find(
        {"status": {"$in": ["open", "closed", "published"]}}
    ).sort("opens_at", 1).to_list(50)

    # ★ candidate_ids ใน round doc เก็บเป็น ObjectId — normalize เป็น str ทั้งตอน lookup และตอน response
    artist_oids = {ObjectId(aid) for r in rounds for aid in r.get("candidate_ids", [])}
    artists = {
        str(a["_id"]): a
        async for a in Col.artists().find({"_id": {"$in": list(artist_oids)}})
    }

    now = datetime.now(timezone.utc)
    out = []
    for r in rounds:
        my_vote = None
        if user:
            my_vote = await get_redis().get(
                K.VOTE_DEDUPE.format(round=r["round_key"], uid=user.id)
            )
        out.append(
            VoteRoundPublic(
                round_key=r["round_key"],
                title=r.get("title", ""),
                status=_effective_status(r, now),
                opens_at=r.get("opens_at"),
                closes_at=r.get("closes_at"),
                results_public=bool(r.get("results_public")),
                max_votes_per_user=r.get("max_votes_per_user", 1),
                candidates=[
                    ArtistPublic(
                        id=aid_str,
                        name=artists.get(aid_str, {}).get("name", "?"),
                        image_url=artists.get(aid_str, {}).get("image_url"),
                        sort_order=artists.get(aid_str, {}).get("sort_order", 0),
                    )
                    for aid in r.get("candidate_ids", [])
                    for aid_str in [str(aid)]
                    if aid_str in artists
                ],
                my_vote=my_vote,
            )
        )
    return out


@rounds_router.get("/{round_key}/results")
async def get_results(round_key: str, user: OptionalUserDep):
    rnd = await _get_round_cached(round_key)
    if not rnd:
        raise not_found("รอบโหวต")

    is_admin = bool(user and user.has("admin", "superadmin"))
    if not rnd.get("results_public") and not is_admin:
        raise forbidden("RESULTS_HIDDEN", "ผลโหวตจะเปิดเผยหลังปิดรอบ")

    tally = await get_redis().hgetall(K.VOTE_TALLY.format(round=round_key))
    total = sum(int(v) for v in tally.values()) or 1

    artists = {
        str(a["_id"]): a.get("name", "?")
        async for a in Col.artists().find(
            {"_id": {"$in": [ObjectId(a) for a in tally]}}, {"name": 1}
        )
    }

    results = sorted(
        (
            {
                "artist_id": aid,
                "name": artists.get(aid, "?"),
                "votes": int(v),
                "percent": round(int(v) * 100 / total, 1),
            }
            for aid, v in tally.items()
        ),
        key=lambda x: -x["votes"],
    )

    return {
        "round_key": round_key,
        "total_votes": sum(int(v) for v in tally.values()),
        "results": results,
        "as_of": datetime.now(timezone.utc),
        "is_final": rnd["status"] in ("closed", "published"),
    }


# ── helpers ────────────────────────────────────────────────────────────
def _effective_status(rnd: dict, now: datetime) -> str:
    """สถานะที่ "จริง" ตอนนี้ — เอานาฬิกามาคิดด้วย ไม่ใช่ดูแค่ฟิลด์ status

    ★ ปัญหาที่เจอจริง: รอบที่ status=open แต่ closes_at ผ่านไปแล้ว
      (เกิดตลอดถ้า staff ลืมกดปิด) หน้า /vote กรองด้วย status=="open"
      เลยยังโชว์ว่าโหวตได้ แต่พอกดจริง POST /votes เด้ง "หมดเวลาโหวตแล้ว"
      → ผู้ใช้เห็นปุ่มที่กดแล้ว error ซึ่งหน้างานจะโดนถามเยอะมาก
      คืนสถานะที่ตรงกับความจริงตั้งแต่ตอน list เลย ทุก client จะเห็นตรงกัน
    """
    status = rnd.get("status", "draft")
    if status != "open":
        return status
    if rnd.get("closes_at") and now > _as_utc(rnd["closes_at"]):
        return "closed"
    if rnd.get("opens_at") and now < _as_utc(rnd["opens_at"]):
        return "scheduled"
    return "open"


async def _get_round_cached(round_key: str) -> dict | None:
    """cache รอบโหวต 3 วินาที

    ถ้าไม่ cache → 1,500 rps จะยิง Mongo 1,500 ครั้ง/วิ เพื่ออ่านของเดิมซ้ำๆ
    3 วิ พอเหมาะ: admin กดปิดรอบแล้วมีผลใน 3 วิ ยอมรับได้
    """
    r = get_redis()
    ck = f"round:{round_key}"
    if cached := await r.get(ck):
        return json.loads(cached)

    doc = await Col.vote_rounds().find_one({"round_key": round_key})
    if not doc:
        return None

    doc["_id"] = str(doc["_id"])
    doc["candidate_ids"] = [str(a) for a in doc.get("candidate_ids", [])]
    await r.set(ck, json.dumps(doc, default=str), ex=3)
    return doc


def _as_utc(v) -> datetime:
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
