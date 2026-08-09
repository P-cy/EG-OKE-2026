"""Wheel — provably fair, server-authoritative

หลักการ:
  · ผลตัดสินที่ server เท่านั้น frontend มีหน้าที่ animate ให้หยุดตรง segment_index
  · commit–reveal: ประกาศ sha256(server_seed) ก่อนงาน, เปิดเผย seed หลังงาน
    → ใครก็ตรวจสอบย้อนหลังได้ว่าเราไม่ได้แก้ผล
"""
import hashlib
import hmac
import secrets

from app.core.config import settings


def new_server_seed() -> tuple[str, str]:
    """คืน (server_seed, commit_hash) — ประกาศ commit_hash ก่อนงาน"""
    seed = secrets.token_hex(32)
    return seed, commit_hash(seed)


def commit_hash(server_seed: str) -> str:
    return "sha256:" + hashlib.sha256(server_seed.encode()).hexdigest()


def compute_result(
    segments: list[dict],
    client_seed: str,
    nonce: int,
    server_seed: str | None = None,
) -> tuple[int, dict, str]:
    """คืน (segment_index, segment, hmac_hex)

    ใช้ HMAC แทน random() เพราะ:
      1. ทำซ้ำได้ → พิสูจน์ได้ว่าไม่โกง
      2. คาดเดาไม่ได้ถ้าไม่รู้ server_seed
      3. ไม่ต้องเก็บ state ของ RNG
    """
    seed = server_seed or settings.WHEEL_SERVER_SEED
    if not seed:
        raise RuntimeError("WHEEL_SERVER_SEED ไม่ได้ตั้งค่า")

    msg = f"{client_seed}:{nonce}"
    digest = hmac.new(seed.encode(), msg.encode(), hashlib.sha256).hexdigest()

    total_weight = sum(int(s.get("weight", 0)) for s in segments)
    if total_weight <= 0:
        raise ValueError("ผลรวม weight ต้องมากกว่า 0")

    # ใช้ 32 bit แรกของ digest — พอสำหรับ total_weight ระดับล้าน
    n = int(digest[:8], 16)
    target = n % total_weight

    cumulative = 0
    for idx, seg in enumerate(segments):
        cumulative += int(seg.get("weight", 0))
        if target < cumulative:
            return idx, seg, digest

    # ไม่ควรถึงตรงนี้ แต่กันไว้
    return len(segments) - 1, segments[-1], digest


def verify(
    server_seed: str,
    client_seed: str,
    nonce: int,
    segments: list[dict],
    expected_index: int,
) -> bool:
    """ให้ผู้ใช้ตรวจสอบย้อนหลังหลังงาน"""
    idx, _, _ = compute_result(segments, client_seed, nonce, server_seed)
    return idx == expected_index


def fallback_segment(segments: list[dict]) -> tuple[int, dict]:
    """ถ้าของหมด ตกไปช่อง 'ไม่ถูกรางวัล'

    หา segment ที่ prize_type == 'none' ตัวแรก
    """
    for idx, seg in enumerate(segments):
        if seg.get("prize_type") == "none":
            return idx, seg
    return len(segments) - 1, segments[-1]
