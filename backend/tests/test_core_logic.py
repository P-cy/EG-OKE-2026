"""ทดสอบ logic ที่พลาดแล้วเจ็บ — รันด้วย: pytest tests/ -v

ครอบคลุม:
  · QR HMAC — ปลอมไม่ได้
  · TOTP — anti-screenshot
  · Wheel — deterministic + การกระจายตรงกับ weight
  · vote.lua — โหวตซ้ำ 10,000 ครั้งต้องนับครั้งเดียว  ★ ข้อสำคัญที่สุด
  · ratelimit.lua — sliding window แม่นยำ
"""
import collections
import hashlib
import time

import pytest

from app.core.security import (
    build_qr_payload, hash_ip, totp_now, totp_verify, verify_qr_payload,
)
from app.services import wheel_engine

TICKET = "EGOKE26-7F3A9C21"     # รูปแบบปัจจุบัน: 1 บัตร/คน ไม่ฝังเลขวันแล้ว

SEGMENTS = [
    {"id": "s1", "label": "เสื้อ", "weight": 5, "prize_type": "physical"},
    {"id": "s2", "label": "+100", "weight": 50, "prize_type": "points", "points": 100},
    {"id": "s3", "label": "+50", "weight": 200, "prize_type": "points", "points": 50},
    {"id": "s4", "label": "+10", "weight": 400, "prize_type": "points", "points": 10},
    {"id": "s5", "label": "ไม่ถูกรางวัล", "weight": 345, "prize_type": "none"},
]


# ── QR ─────────────────────────────────────────────────────────────────
def test_qr_roundtrip():
    ok, code, _ = verify_qr_payload(build_qr_payload(TICKET))
    assert ok and code == TICKET


def test_qr_tampered_signature_rejected():
    p = build_qr_payload(TICKET)
    tampered = p[:-3] + ("AAA" if not p.endswith("AAA") else "BBB")
    ok, _, reason = verify_qr_payload(tampered)
    assert not ok and reason == "invalid_sig"


def test_qr_swapped_ticket_code_rejected():
    """คนแก้ ticket_code ในเข้ารหัสเพื่อเข้างานแทนคนอื่น"""
    parts = build_qr_payload(TICKET).split(":")
    parts[2] = "EGOKE26-DEADBEEF"
    ok, _, _ = verify_qr_payload(":".join(parts))
    assert not ok


def test_qr_malformed_rejected():
    assert not verify_qr_payload("garbage")[0]
    assert not verify_qr_payload("")[0]


# ── TOTP ───────────────────────────────────────────────────────────────
def test_totp_current_code_valid():
    assert totp_verify(TICKET, totp_now(TICKET))


def test_totp_rejects_other_ticket():
    assert not totp_verify("EGOKE26-0THER000", totp_now(TICKET))


def test_totp_rejects_old_screenshot():
    """★ นี่คือกลไกกันคนแคปหน้าจอส่งให้เพื่อน"""
    now = int(time.time())
    old = totp_now(TICKET, now - 150)  # 5 periods ที่แล้ว
    assert not totp_verify(TICKET, old, now)


def test_totp_tolerates_clock_drift():
    """scanner นาฬิกาเพี้ยน ±1 period ต้องยังผ่าน"""
    now = int(time.time())
    assert totp_verify(TICKET, totp_now(TICKET, now - 30), now)


# ── Wheel ──────────────────────────────────────────────────────────────
def test_wheel_deterministic():
    seed, _ = wheel_engine.new_server_seed()
    a = wheel_engine.compute_result(SEGMENTS, "abc", 1, seed)[0]
    b = wheel_engine.compute_result(SEGMENTS, "abc", 1, seed)[0]
    assert a == b


def test_wheel_commit_hash_provable():
    seed, commit = wheel_engine.new_server_seed()
    assert commit == "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


def test_wheel_verify_catches_wrong_index():
    seed, _ = wheel_engine.new_server_seed()
    idx = wheel_engine.compute_result(SEGMENTS, "abc", 1, seed)[0]
    assert wheel_engine.verify(seed, "abc", 1, SEGMENTS, idx)
    assert not wheel_engine.verify(seed, "abc", 1, SEGMENTS, (idx + 1) % len(SEGMENTS))


def test_wheel_distribution_matches_weights():
    """การกระจายต้องตรงกับ weight ที่ประกาศ — ไม่งั้นโดนกล่าวหาว่าโกง"""
    seed, _ = wheel_engine.new_server_seed()
    n = 100_000
    cnt = collections.Counter(
        wheel_engine.compute_result(SEGMENTS, "s", i, seed)[0] for i in range(n)
    )
    total_w = sum(s["weight"] for s in SEGMENTS)
    for i, seg in enumerate(SEGMENTS):
        expected = seg["weight"] * 100 / total_w
        actual = cnt[i] * 100 / n
        assert abs(expected - actual) < 0.7, f"{seg['id']}: {expected:.2f}% vs {actual:.2f}%"


def test_wheel_fallback_is_no_prize():
    _, seg = wheel_engine.fallback_segment(SEGMENTS)
    assert seg["prize_type"] == "none"


# ── Privacy ────────────────────────────────────────────────────────────
def test_ip_never_stored_raw():
    h = hash_ip("203.0.113.42")
    assert "203.0.113" not in h
    assert h == hash_ip("203.0.113.42")       # stable
    assert h != hash_ip("203.0.113.43")       # distinct


# ── Lua scripts (ต้องมี fakeredis[lua]) ───────────────────────────────
@pytest.mark.asyncio
async def test_vote_lua_dedupe_under_spam():
    """★ การทดสอบที่สำคัญที่สุดในไฟล์นี้

    1,000 คนโหวตคนละครั้ง แล้วทุกคน retry อีกคนละ 10 ครั้ง
    → ต้องนับได้ 1,000 พอดี ไม่ใช่ 11,000
    """
    import fakeredis.aioredis as fr

    r = fr.FakeRedis(decode_responses=True)
    vote = r.register_script(open("app/lua/vote.lua").read())

    async def cast(uid: str, artist: str):
        return await vote(
            keys=["vote:d1:" + uid, "tally:d1", "lb:d1", "stream:votes"],
            args=[uid, artist, "d1", 3600, int(time.time() * 1000), "iphash", 100000],
        )

    for i in range(1000):
        await cast(f"u{i}", "A" if i % 2 == 0 else "B")
    baseline = await r.hgetall("tally:d1")
    assert int(baseline["A"]) == 500 and int(baseline["B"]) == 500

    # ทุกคน spam ซ้ำ 10 ครั้ง (จำลองเน็ตช้าแล้วผู้ใช้กดรัว)
    for i in range(1000):
        for _ in range(10):
            await cast(f"u{i}", "A")

    assert await r.hgetall("tally:d1") == baseline, "โหวตซ้ำทำให้คะแนนเพี้ยน!"
    assert await r.xlen("stream:votes") == 1000, "stream มีรายการเกิน = worker จะเขียนซ้ำ"


@pytest.mark.asyncio
async def test_vote_lua_returns_original_choice_on_duplicate():
    """โหวต A แล้วเปลี่ยนใจโหวต B → ต้องได้ A เหมือนเดิม ไม่ใช่ error"""
    import fakeredis.aioredis as fr

    r = fr.FakeRedis(decode_responses=True)
    vote = r.register_script(open("app/lua/vote.lua").read())
    keys = ["vote:d1:u1", "tally:d1", "lb:d1", "stream:votes"]
    def args(a):
        return ["u1", a, "d1", 3600, int(time.time() * 1000), "ip", 1000]

    accepted, artist, _ = await vote(keys=keys, args=args("A"))
    assert int(accepted) == 1 and artist == "A"

    accepted2, artist2, _ = await vote(keys=keys, args=args("B"))
    assert int(accepted2) == 0 and artist2 == "A"
    assert await r.hget("tally:d1", "B") is None


@pytest.mark.asyncio
async def test_ratelimit_lua_enforces_limit():
    import fakeredis.aioredis as fr

    r = fr.FakeRedis(decode_responses=True)
    rl = r.register_script(open("app/lua/ratelimit.lua").read())

    async def hit(ident: str, limit: int = 5, window: int = 60):
        now = time.time()
        idx = int(now // window)
        return await rl(
            keys=[f"rl:t:{ident}:{idx}", f"rl:t:{ident}:{idx - 1}"],
            args=[limit, window, f"{(now % window) / window:.4f}"],
        )

    allowed = 0
    for _ in range(10):
        result = await hit("ip1")
        allowed += int(result[0])
    assert allowed == 5

    blocked, _, retry = await hit("ip1")
    assert int(blocked) == 0 and int(retry) > 0

    other, _, _ = await hit("ip2")
    assert int(other) == 1, "rate limit ไม่ควรกระทบ identity อื่น"
