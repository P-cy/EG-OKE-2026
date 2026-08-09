# EG'OKE 2026 — Backend

FastAPI + MongoDB + Redis · ออกแบบให้รับ burst 1,500 rps และไม่ล่มแม้ MongoDB ตาย

เอกสารออกแบบเต็มอยู่ที่ [`../docs/`](../docs/)

## เริ่มใช้งาน (local)

```bash
cd backend
cp .env.example .env

# สร้าง secret จริง (อย่าใช้ค่า CHANGE_ME)
for k in JWT_SECRET QR_SIGNING_KEY TOTP_KEY WHEEL_SERVER_SEED; do
  echo "$k=$(openssl rand -hex 32)"
done
echo "IP_PEPPER=$(openssl rand -hex 16)"
# → เอาไปแทนใน .env

docker compose up -d
docker compose exec api python -m scripts.init_indexes   # ★ ห้ามข้าม
docker compose exec api python -m scripts.seed_dev

curl localhost:8000/healthz
open http://localhost:8000/docs
```

สำหรับ load test: `python -m scripts.seed_dev --users 5000`

## โครงสร้าง

```
app/
├── main.py            REST API (gunicorn ×4)
├── ws_main.py         WebSocket แยกโปรเซส — restart api แล้วจอไม่หลุด
├── core/
│   ├── config.py      settings + validate_production() ที่ fail fast
│   ├── db.py          Mongo + accessor ทุก collection
│   ├── redis_client.py  Redis + Lua registry + key namespace
│   ├── security.py    JWT, QR HMAC, TOTP, hash_ip
│   ├── deps.py        auth, roles, feature flags, read-only mode
│   ├── ratelimit.py   sliding window
│   ├── errors.py      error model กลาง (ไทย/อังกฤษ + request_id)
│   └── observability.py  structlog + Prometheus + request_id
├── lua/
│   ├── vote.lua       ★ atomic dedupe + tally + queue ใน round-trip เดียว
│   └── ratelimit.lua  sliding window counter
├── routers/           auth · me · checkin · votes · ig · wheel · live · admin · health
├── services/          points (ledger) · wheel_engine · google_oauth
├── realtime/          WS manager + Redis pub/sub fanout + backpressure
└── workers/
    ├── runner.py      ★ drain Redis Stream → Mongo (ตัวที่ทำให้ Mongo ล่มแล้วเว็บไม่ล่ม)
    └── broadcaster.py snapshot ทุก 1 วิ (singleton, Redis lock)
```

## จุดที่ต้องเข้าใจก่อนแก้โค้ด

| จุด | อย่าทำ | ทำแบบนี้ |
|---|---|---|
| `/votes` | เขียน Mongo ตรงๆ | ผ่าน `vote.lua` → Redis Stream → worker |
| ให้คะแนน | `$set points_balance` | `points.award()` ที่จอง idempotency_key ก่อน |
| ผลวงล้อ | สุ่มที่ frontend | `wheel_engine.compute_result()` ที่ server |
| `/live/*` | คำนวณสดทุก request | อ่าน `live:snapshot` ที่ broadcaster เตรียมไว้ |
| Redis eviction | `allkeys-lru` | `noeviction` — ไม่งั้น dedupe key หายเงียบๆ |
| rate limit key | IP (ทุกคนอยู่หลัง NAT เดียวกัน) | `user_id` สำหรับ endpoint ที่มี auth |
| query จาก body | `find_one({"x": body["x"]})` | ผ่าน Pydantic model เสมอ |

## Tests

```bash
pip install "fakeredis[lua]" pytest pytest-asyncio
pytest tests/ -v
```

ผลรัน (verified):

```
17 passed
```

ครอบคลุมข้อที่พลาดแล้วเจ็บ:

- QR HMAC ปลอมไม่ได้ · เปลี่ยน ticket_code ไม่ได้
- TOTP กันแคปหน้าจอ (โค้ดเก่า 150 วิ ใช้ไม่ได้) แต่ทน clock drift ±30 วิ
- Wheel deterministic + การกระจายตรง weight (คลาดเคลื่อน < 0.11pp จาก 200k ครั้ง)
- **`vote.lua`: 1,000 คนโหวต + retry คนละ 10 ครั้ง = 11,000 requests → นับได้ 1,000 พอดี**
- ratelimit.lua จำกัดแม่นยำและไม่กระทบ identity อื่น

## Environment variables

ดู `.env.example` — ตัวที่ห้ามลืมใน production:

```bash
ENV=production
DEBUG=false
ENABLE_DOCS=false          # ★ ไม่งั้น API spec เปิดสาธารณะ
JWT_SECRET=<openssl rand -hex 32>
QR_SIGNING_KEY=<openssl rand -hex 32>
IP_PEPPER=<openssl rand -hex 16>   # ★ ตั้งครั้งเดียว ห้ามเปลี่ยน
```

`settings.validate_production()` จะ raise ตอน startup ถ้าค่าเหล่านี้ไม่ปลอดภัย — **ตายตั้งแต่ boot ดีกว่าโดนแฮกตอนงาน**

## ปุ่มฉุกเฉินหน้างาน

```bash
# ปิดทั้งเว็บ
curl -X PATCH .../v1/admin/config -d '{"maintenance_mode": true}'
# อ่านได้ เขียนไม่ได้ (ใช้ตอนไม่รู้สาเหตุ — หยุดเลือดก่อน)
curl -X PATCH .../v1/admin/config -d '{"read_only_mode": true}'
# ปิดเฉพาะโหวต
curl -X PATCH .../v1/admin/config -d '{"features": {"voting": false}}'
```

มีผลใน 5 วินาที ไม่ต้อง deploy ไม่ต้อง restart
