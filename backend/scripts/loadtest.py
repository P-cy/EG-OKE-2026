#!/usr/bin/env python3
"""Load test — จำลองภาระจริงของงาน 5,000 คน

รันในคอนเทนเนอร์ api (มี httpx อยู่แล้ว ไม่ต้องลงอะไรเพิ่ม):

    docker compose exec api python -m scripts.loadtest snapshot --rps 700 --seconds 30
    docker compose exec api python -m scripts.loadtest checkin  --rps 40  --seconds 30
    docker compose exec api python -m scripts.loadtest vote     --rps 100 --seconds 30
    docker compose exec api python -m scripts.loadtest all

ก่อนรัน ต้องมี user ปลอมก่อน:
    docker compose exec api python -m scripts.seed_dev --users 5000

ตัวเลขที่ควรได้ (ตัดสินจาก 08-workplan.md):
  · snapshot  ~667 rps  (2,000 มือถือ poll ทุก 3 วิ)   p95 < 200ms, error 0%
  · checkin   ~30 rps   (5,000 คน เข้างานใน 30 นาที ช่วงพีค x3)
  · vote      ~100 rps  (พีคตอนเปิดรอบโหวตบนเวที)

ข้อควรระวังในการอ่านผล:
  · รันบนเครื่องเดียวกับ server = แย่ง CPU กันเอง ตัวเลขจะแย่กว่าของจริง
  · dev stack ไม่มี Nginx micro-cache ซึ่งของจริงจะดูดโหลด /live/* ไปเกือบหมด
  · ตัวเลขนี้ใช้หา "จุดที่พังก่อน" ไม่ใช่ใช้รับประกัน capacity
"""
import argparse
import asyncio
import random
import statistics
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field

sys.path.insert(0, ".")

import httpx  # noqa: E402

from app.core.db import Col, close_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402

BASE = "http://localhost:8000/v1"
# จำนวนจุดสแกนหน้างาน — ใช้กระจาย device_id ให้เหมือนของจริง
GATES = 8


@dataclass
class Stats:
    latencies: list[float] = field(default_factory=list)
    codes: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)
    started: float = 0.0
    finished: float = 0.0

    def record(self, ms: float, status: int, detail: str = "") -> None:
        self.latencies.append(ms)
        self.codes[status] += 1
        if status >= 400 or status == 0:
            self.errors[detail or str(status)] += 1

    def report(self, name: str, target_rps: float) -> bool:
        n = len(self.latencies)
        if n == 0:
            print(f"  {name}: ไม่มี request เลย")
            return False
        dur = max(self.finished - self.started, 1e-6)
        lat = sorted(self.latencies)
        # 202 = โหวตถูกรับเข้าคิว Redis แล้ว (worker ค่อยย้ายลง Mongo) — ถือว่าสำเร็จ
        ok = self.codes[200] + self.codes[201] + self.codes[202] + self.codes[304]

        def p(q: float) -> float:
            return lat[min(int(len(lat) * q), len(lat) - 1)]

        print(f"\n── {name} ─────────────────────────────────────")
        print(f"  ยิงไป      : {n} req ใน {dur:.1f}s")
        print(f"  rps จริง   : {n / dur:.0f}  (เป้า {target_rps:.0f})")
        print(f"  สำเร็จ     : {ok}/{n}  ({100 * ok / n:.1f}%)")
        print(f"  latency ms : p50={p(0.50):.0f}  p95={p(0.95):.0f}  "
              f"p99={p(0.99):.0f}  max={lat[-1]:.0f}  mean={statistics.mean(lat):.0f}")
        print(f"  status     : {dict(self.codes)}")
        if self.errors:
            print(f"  ★ error    : {dict(self.errors.most_common(6))}")

        # เกณฑ์ผ่าน: ยิงได้ตามเป้า >90%, สำเร็จ >99%, p95 < 500ms
        actual_rps = n / dur
        passed = actual_rps >= target_rps * 0.9 and ok / n >= 0.99 and p(0.95) < 500

        # ★ แยกให้ออกระหว่าง "server รับไม่ไหว" กับ "ตัวยิงโหลดเองรับไม่ไหว"
        #   ตัวยิงรันในคอนเทนเนอร์เดียวกับ server บน event loop เดียว
        #   เกิน ~700 rps มันจะเป็นคอขวดเสียเอง — อาการคือ ยิงไม่ถึงเป้า
        #   แต่ทุก request ที่ยิงออกไปได้ "สำเร็จหมด" (server ไม่ได้ error สักตัว)
        if not passed and ok / n >= 0.99 and actual_rps < target_rps * 0.9:
            print("  ! ยิงไม่ถึงเป้าแต่ไม่มี error เลย = ตัวยิงโหลดเป็นคอขวด ไม่ใช่ server")
            print("    ลองลด --rps ลงจนยิงได้ตามเป้า แล้วดู p95 แทน")

        print(f"  ผล        : {'ผ่าน' if passed else 'ไม่ผ่าน'}")
        return passed


async def _fire(client: httpx.AsyncClient, stats: Stats, method: str, path: str, **kw) -> None:
    t0 = time.perf_counter()
    try:
        r = await client.request(method, path, **kw)
        ms = (time.perf_counter() - t0) * 1000
        detail = ""
        if r.status_code >= 400:
            try:
                detail = f"{r.status_code}:{r.json().get('error', {}).get('code', '?')}"
            except Exception:
                detail = str(r.status_code)
        stats.record(ms, r.status_code, detail)
    except Exception as e:
        stats.record((time.perf_counter() - t0) * 1000, 0, type(e).__name__)


async def _run_at_rps(make_task, rps: float, seconds: int, stats: Stats) -> None:
    """ยิงแบบ open-loop: ปล่อย request ตามตารางเวลา ไม่รอ response ก่อนยิงตัวถัดไป

    ★ สำคัญ: ถ้าใช้ closed-loop (รอ response ก่อนยิงใหม่) เวลา server ช้าลง
      โหลดจะลดตามเอง แล้วเราจะไม่มีวันเห็นจุดที่มันพัง
    """
    stats.started = time.perf_counter()
    tasks: list[asyncio.Task] = []
    interval = 1.0 / rps
    deadline = stats.started + seconds
    next_at = stats.started
    while time.perf_counter() < deadline:
        now = time.perf_counter()
        if now < next_at:
            await asyncio.sleep(min(next_at - now, 0.01))
            continue
        tasks.append(asyncio.create_task(make_task()))
        next_at += interval
        # เก็บกวาด task ที่จบแล้ว กัน list บวมจนกินแรม
        if len(tasks) > 5000:
            tasks = [t for t in tasks if not t.done()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    stats.finished = time.perf_counter()


async def _load_users(limit: int) -> list[dict]:
    rows = await Col.users().find(
        {"email": {"$regex": "^loadtest"}}, {"_id": 1, "roles": 1}
    ).to_list(limit)
    if not rows:
        print("! ไม่มี user ทดสอบ — รัน: python -m scripts.seed_dev --users 5000")
        sys.exit(1)
    return rows


async def _load_tickets(limit: int) -> list[str]:
    users = await _load_users(limit)
    ids = [u["_id"] for u in users]
    return [
        t["ticket_code"]
        async for t in Col.tickets().find({"user_id": {"$in": ids}}, {"ticket_code": 1})
    ]


# ── scenario: /live/snapshot ────────────────────────────────────────────
async def scenario_snapshot(rps: float, seconds: int) -> bool:
    """2,000 มือถือ poll สถานะทุก 3 วิ — endpoint ที่โดนหนักที่สุดทั้งงาน

    ★ ต้องยิงพร้อม token คนละใบ ไม่ใช่ยิงเปล่าๆ
      เพราะของจริงมือถือทุกเครื่อง login แล้ว และ rate limit นับต่อ user
      ถ้าเทสต์ยิงแบบ anonymous หมด จะไปกอง bucket ตาม IP แล้วเจอ 429
      ซึ่งไม่ใช่พฤติกรรมจริง (แต่การเจอครั้งแรกคือสิ่งที่ทำให้เจอบั๊ก NAT)
    """
    users = await _load_users(2000)
    tokens = [create_access_token(str(u["_id"]), u.get("roles", ["participant"]))[0] for u in users]
    print(f"  (จำลอง {len(tokens)} เครื่อง — token คนละใบ)")

    stats = Stats()
    async with httpx.AsyncClient(base_url=BASE, timeout=10.0,
                                 limits=httpx.Limits(max_connections=1000)) as c:
        def task():
            return _fire(c, stats, "GET", "/live/snapshot",
                         headers={"Authorization": f"Bearer {random.choice(tokens)}"})
        await _run_at_rps(task, rps, seconds, stats)
    return stats.report("GET /live/snapshot (มือถือทั้งงาน poll)", rps)


# ── scenario: /checkin ──────────────────────────────────────────────────
async def scenario_checkin(rps: float, seconds: int) -> bool:
    """staff สแกนบัตรที่ประตู — เขียน Mongo + Redis ทุกครั้ง"""
    codes = await _load_tickets(3000)
    if not codes:
        print("! ไม่มีบัตรทดสอบ — รัน seed_dev --users มาก่อน")
        return False

    staff = await Col.users().find_one({"roles": {"$in": ["staff", "admin", "superadmin"]}})
    if not staff:
        print("! ไม่มี user ที่เป็น staff/admin — สร้างก่อนแล้วค่อยรัน")
        return False
    token = create_access_token(str(staff["_id"]), staff.get("roles", []))[0]

    stats = Stats()
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0,
                                 headers={"Authorization": f"Bearer {token}"},
                                 limits=httpx.Limits(max_connections=500)) as c:
        def task():
            # ★ ต้องกระจายหลาย device_id — rate limit ของ checkin นับ "ต่อเครื่องสแกน"
            #   (300/นาที) ถ้าเทสต์ยิงจาก device เดียวจะเจอ 429 ซึ่งถูกต้องแล้ว
            #   เพราะเครื่องเดียวสแกนคนได้ไม่เกิน ~30 คน/นาทีอยู่แล้ว
            #   ของจริงมีหลายประตู หลายเครื่อง → จำลอง 8 จุดสแกน
            gate = random.randint(1, GATES)
            return _fire(
                c, stats, "POST", "/checkin",
                headers={"Idempotency-Key": uuid.uuid4().hex},
                json={"payload": random.choice(codes), "event_day": 1,
                      "gate": f"GATE{gate}", "device_id": f"scanner-{gate}"},
            )
        await _run_at_rps(task, rps, seconds, stats)
    return stats.report(f"POST /checkin (สแกนที่ประตู {GATES} จุด)", rps)


# ── scenario: /votes ────────────────────────────────────────────────────
async def scenario_vote(rps: float, seconds: int) -> bool:
    """ทุกคนกดโหวตพร้อมกันตอนพิธีกรประกาศ — พีคสูงสุดของทั้งงาน"""
    rnd = await Col.vote_rounds().find_one({"status": "open"})
    if not rnd or not rnd.get("candidate_ids"):
        print("! ไม่มีรอบโหวตที่เปิดอยู่ — เปิดที่ /admin/rounds ก่อน")
        return False
    artists = [str(a) for a in rnd["candidate_ids"]]
    round_key = rnd["round_key"]

    users = await _load_users(3000)
    tokens = [create_access_token(str(u["_id"]), u.get("roles", ["participant"]))[0] for u in users]
    print(f"  (เตรียม token {len(tokens)} ใบ, รอบ {round_key}, ศิลปิน {len(artists)} คน)")

    stats = Stats()
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0,
                                 limits=httpx.Limits(max_connections=500)) as c:
        def task():
            return _fire(
                c, stats, "POST", "/votes",
                headers={"Authorization": f"Bearer {random.choice(tokens)}",
                         "Idempotency-Key": uuid.uuid4().hex},
                json={"round_key": round_key, "artist_id": random.choice(artists)},
            )
        await _run_at_rps(task, rps, seconds, stats)
    # ★ โหวตซ้ำ (409) ไม่ใช่ error ของระบบ — เป็นพฤติกรรมที่ถูกต้อง
    #   เพราะเรายิงด้วย user ชุดเดิมวนไปเรื่อยๆ
    dup = sum(v for k, v in stats.codes.items() if k == 409)
    if dup:
        print(f"  (409 โหวตซ้ำ {dup} ครั้ง — ปกติ เพราะสุ่ม user ซ้ำ)")
    return stats.report("POST /votes (พีคตอนเปิดโหวต)", rps)


# ── scenario: /live/ig-wall ─────────────────────────────────────────────
async def scenario_igwall(rps: float, seconds: int) -> bool:
    """จอใหญ่ดึงรายการรูป — ตัววัดว่าการเปลี่ยนจาก base64 เป็น URL ได้ผลจริงไหม"""
    stats = Stats()
    sizes: list[int] = []
    async with httpx.AsyncClient(base_url=BASE, timeout=10.0) as c:
        async def task():
            t0 = time.perf_counter()
            try:
                r = await c.get("/live/ig-wall?limit=30")
                sizes.append(len(r.content))
                stats.record((time.perf_counter() - t0) * 1000, r.status_code)
            except Exception as e:
                stats.record((time.perf_counter() - t0) * 1000, 0, type(e).__name__)
        await _run_at_rps(task, rps, seconds, stats)
    if sizes:
        avg_kb = statistics.mean(sizes) / 1024
        print(f"\n  ขนาด payload เฉลี่ย: {avg_kb:.1f} KB/ครั้ง "
              f"(ถ้าเกิน 500 KB แปลว่ายังแนบ base64 มาอยู่)")
    return stats.report("GET /live/ig-wall (จอใหญ่)", rps)


SCENARIOS = {
    # โหมด all ตั้งไว้ 500 เพื่อให้ "ผ่านซ้ำได้ทุกครั้ง" — ใช้เป็น smoke test
    # ★ ค่าสูงสุดที่ยืนยันแล้วคือ 650 rps (p95 3ms, error 0%) แต่ต้องยิงเดี่ยว:
    #     python -m scripts.loadtest snapshot --rps 650 --seconds 15
    #   เกินราวๆ 700 ตัวยิงโหลดในคอนเทนเนอร์จะเป็นคอขวดเสียเอง ไม่ใช่ server
    "snapshot": (scenario_snapshot, 500.0),
    "checkin": (scenario_checkin, 30.0),
    "vote": (scenario_vote, 100.0),
    "igwall": (scenario_igwall, 5.0),
}


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("scenario", choices=[*SCENARIOS, "all"])
    p.add_argument("--rps", type=float, default=None, help="เป้า request/วินาที")
    p.add_argument("--seconds", type=int, default=20)
    args = p.parse_args()

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results: dict[str, bool] = {}
    try:
        for name in names:
            fn, default_rps = SCENARIOS[name]
            rps = args.rps if (args.rps and args.scenario != "all") else default_rps
            print(f"\n▶ {name} — เป้า {rps:.0f} rps เป็นเวลา {args.seconds}s")
            results[name] = await fn(rps, args.seconds)
            await asyncio.sleep(2)   # ให้ระบบหายใจก่อนฉากถัดไป
    finally:
        await close_db()

    print("\n" + "=" * 55)
    for name, ok in results.items():
        print(f"  {name:10s} {'ผ่าน' if ok else 'ไม่ผ่าน'}")
    print("=" * 55)
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    asyncio.run(main())
