# 18 — Backend Handoff (ส่งต่อทีม Backend / DevOps)

> คู่กับ [15-frontend-handoff.md](15-frontend-handoff.md) (ฝั่งเว็บ)
> ที่นี่: tech stack, โครงโฟลเดอร์, รัน dev, build+docker, env, services, ops

## Tech stack

| ตัว | เวอร์ชัน | หมายเหตุ |
|---|---|---|
| Python | 3.12 | Dockerfile `python:3.12-slim` |
| FastAPI | (ใน requirements.txt) | async, REST |
| MongoDB | 7 (replica set) | `motor` async driver |
| Redis | 7 | cache + realtime bus + Lua |
| Pydantic v2 + pydantic-settings | | validation + config |
| httpx | | Google OAuth + SlipOK (removed) |
| gunicorn + uvicorn worker | | production (4 workers) |
| structlog + prometheus-client | | logging + metrics |

## โครงสร้างโฟลเดอร์

```
backend/
├── app/
│   ├── main.py                 # ★ REST API (FastAPI) — process หลัก
│   ├── ws_main.py              # ★ WebSocket server (process แยก, สำหรับจอ display)
│   ├── routers/                # endpoint แยกตามโดเมน (admin/auth/checkin/ig/live/me/quests/staff/votes/wheel/exports/avatars/health)
│   ├── services/               # business logic (coins/tickets/profile/wheel_engine/google_oauth/grant_limits/audit/attendance)
│   ├── core/                   # config/db/redis/deps/errors/security/observability/ratelimit/gzip
│   ├── realtime/               # manager (WS fanout) + notify_manager (SSE per-user demux)
│   ├── workers/                # runner (drain vote stream → Mongo + reconcile) + broadcaster (snapshot ทุก 1s)
│   ├── models/schemas.py       # Pydantic models (input validation ทั้งหมด)
│   └── lua/                    # vote.lua (atomic vote)
├── scripts/                    # init_indexes, seed_dev, import_artists, reset_user, loadtest, backup.sh
├── tests/                      # pytest (contract tests ฝั่ง frontend ด้วย)
├── Dockerfile                  # ภาพเดียวใช้ทุก service (api/ws/worker/broadcaster เลือกด้วย CMD)
├── docker-compose.yml          # dev (6 services)
├── docker-compose.prod.yml     # production (+ nginx + certbot + web)
├── nginx/                      # nginx config template
├── requirements.txt
├── pytest.ini
└── .env / .env.example
```

## การรัน — Development

### ทางเร็ว: Docker Compose (แนะนำ)
```bash
cd backend
cp .env.example .env          # ครั้งแรก — แก้ GOOGLE_CLIENT_ID/SECRET (ดู [11-local-testing-guide.md](11-local-testing-guide.md))
docker compose up -d          # สร้าง+start ทุก service
docker compose logs -f api    # ดู log
```

services ที่ขึ้น (6 ตัว):
| service | ทำอะไร | port |
|---|---|---|
| `mongo` | MongoDB 7 replica set (`--replSet rs0` — ต้องใช้ transactions + change stream) | 27017 |
| `mongo-init` | initiate replica set ครั้งเดียว (one-shot) | — |
| `redis` | Redis 7 (`appendonly yes`, `maxmemory 512mb no-eviction`) | 6379 |
| `api` | **REST API** — `uvicorn app.main:app --reload` | 8000 |
| `ws` | **WebSocket** (จอ display) — `uvicorn app.ws_main:app` | 8001 |
| `worker` | drain vote stream → Mongo + reconcile coins ทุก 5 นาที | — |
| `broadcaster` | สร้าง snapshot ทุก 1 วิ + publish event | — |

### ครั้งแรกหลัง up — ต้องรัน 2 อย่างนี้
```bash
docker compose exec api python -m scripts.init_indexes    # สร้าง index + seed system_config (idempotent)
docker compose exec api python -m scripts.seed_dev        # seed ศิลปิน + รอบโหวต + wheel + quests (ไม่มี user ปลอม)
# อยาก load test: python -m scripts.seed_dev --users 500
```

### ทางเลือก: รันเครื่องตัวเอง (ไม่ใช้ Docker) — เฉพาะ api/ws/worker/broadcaster
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# ต้องมี mongo + redis รันอยู่ (docker compose up -d mongo redis)
uvicorn app.main:app --reload --port 8000          # terminal 1: REST
uvicorn app.ws_main:app --port 8001                # terminal 2: WS
python -m app.workers.runner                       # terminal 3: worker
python -m app.workers.broadcaster                  # terminal 4: broadcaster
```

## การรัน — Production (Docker)

### Build ภาพ
```bash
cd backend
docker build \
  --build-arg GIT_SHA=$(git rev-parse --short HEAD) \
  --build-arg BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  -t egoke-api:latest .
```
ภาพเดียวใช้ได้ทุก service — เลือกด้วย CMD:
- `gunicorn app.main:app ...` (default — REST API, 4 workers)
- `uvicorn app.ws_main:app --port 8001` (WS)
- `python -m app.workers.runner` (worker)
- `python -m app.workers.broadcaster` (broadcaster)

### Full stack production
ดู [14-deploy-vps.md](14-deploy-vps.md) แบบเต็ม — สรุป:
```bash
docker compose -f docker-compose.prod.yml up -d
```
prod compose เพิ่ม: `web` (frontend build), `nginx` (reverse proxy + TLS), `certbot` — mongo/redis/api/ws ไม่ expose port (อยู่หลัง nginx)

## การแก้ .env — ★ สำคัญ

> ⚠️ `docker compose restart` **ไม่อ่าน .env ใหม่** — env ถูกฝังตอนสร้าง container
> แก้ .env แล้วต้อง `docker compose up -d --force-recreate` (หรือ `--build` ถ้าแก้ Dockerfile) ถึงจะมีผล
> api พิมพ์ค่าที่ "มีผลจริง" ตอนบูตใน log (`auth_policy_effective`, `grant_limits_effective`) — เช็คตรงนั้นก่อนหาสาเหตุ

### ค่าที่ต้องตั้งเอง (อย่างอื่นมี default พอใช้)
| Key | ตั้งค่า | หมายเหตุ |
|---|---|---|
| `GOOGLE_CLIENT_ID` | จาก Google Cloud Console | ดู [11](11-local-testing-guide.md) |
| `GOOGLE_CLIENT_SECRET` | จาก Google Cloud Console | |
| `GOOGLE_REDIRECT_URI` | `http://localhost:3000/login` | ต้องตรง Google Console |
| `ADMIN_EMAILS` | email ของคุณ (คั่นจุลภาค) | promote เป็น admin ตอน login |
| `ATTENDANCE_FORM_URL` | Google Form link | ว่าง = ซ่อนปุ่ม modal |

### ค่าลับ — ต้อง generate (prod ต้องยาว ≥32)
```bash
openssl rand -hex 32    # ใช้สำหรับ JWT_SECRET, QR_SIGNING_KEY, TOTP_KEY, WHEEL_SERVER_SEED
openssl rand -hex 16    # IP_PEPPER
```

### ค่าสำคัญอื่น (มี default แต่ควรเข้าใจ)
| Key | Default | หมายเหตุ |
|---|---|---|
| `ENV` | `development` | `production` เปิด validate_production (fail fast ถ้า secret ไม่ปลอดภัย) |
| `ENABLE_DOCS` | `false` | `true` = เปิด `/docs` (ปิดใน prod) |
| `ALLOWED_EMAIL_DOMAINS` | `""` | **ว่าง = รับทุก domain** (คนหน้างานไม่ได้ล็อกอินเมลมหิดล) |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | คั่นจุลภาคได้หลาย origin (LAN IP) |
| `CHECKIN_COINS` | `10` | coin ต่อวันเช็คอิน |
| `STAFF_GRANT_*` | `200/300/1500/20000` | quota 4 ชั้น staff grant (ดู [16](16-features.md#4-quests-กิจกรรมบูธ)) |
| `STRICT_QR_MODE` | `false` | true = บังคับ TOTP rotating code (scanner ต้อง sync NTP) |
| `REQUIRE_CHECKIN_TO_VOTE` | `false` | ต้องเช็คอินก่อนโหวต |
| `DISPLAY_TOKEN` | random | gate WS + `ig-wall/shown` |
| `TOKEN_VERSION` | `1` | bump = kill token ทุกใบทันที (kill-switch) |
| `QR_VERSION` | `1` | bump = ยกเลิก QR เก่าทั้งหมด |

ดู `app/core/config.py` สำหรับรายการเต็ม + `.env.example` สำหรับคอมเมนต์อธิบายแต่ละตัว

## Services โปรเซสแยกกัน — ทำไม

| process | ทำไมแยก |
|---|---|
| `api` (REST) | เปลี่ยนบ่อย → restart บ่อย |
| `ws` (WebSocket) | ถือ connection ยาว — แยกไว้ restart api แล้วจอไม่หลุด |
| `worker` | drain vote stream → Mongo (Mongo ล่มก็โหวตได้ เพราะเก็บใน Redis ก่อน) |
| `broadcaster` | singleton (lock Redis กันซ้ำ) — snapshot ทุก 1 วิ |

## สคริปต์สำคัญ (`scripts/`)

| สคริปต์ | ใช้ตอนไหน |
|---|---|
| `init_indexes.py` | **ทุกครั้งหลัง deploy** — สร้าง index (idempotent) + drop index ตกยุค + seed system_config |
| `seed_dev.py` | dev — seed ศิลปิน/รอบ/wheel/quests + (ถ้ามี `--users N`) user ปลอม load test |
| `import_artists.py data/artists.json` | prod — import ศิลปินจริง (default status `closed` กันเปิดโหวตพลาด) |
| `reset_user.py <email>` | dev — ลบ user ทั้งหมดเพื่อทดสอบ flow login ใหม่ (`--checkin-only` เก็บ user แค่ reset check-in) |
| `loadtest.py` | load test |
| `backup.sh`, `deploy-cert.sh`, `deploy-init.sh` | ops/deploy |

## ตรวจสอบระบบ

```bash
# health (public)
curl localhost:8000/healthz     # 200 = process มีชีวิต
curl localhost:8000/readyz      # 503 ถ้า Redis down (Mongo down = degraded ไม่ใช่ 503)
curl localhost:8000/version     # APP_VERSION + GIT_SHA + BUILD_TIME + ENV

# metrics (IP allowlist METRICS_ALLOWED_IPS)
curl localhost:8000/metrics     # Prometheus format

# ดูใน DB
docker compose exec mongo mongosh egoke2026 --eval 'db.users.countDocuments({})'
docker compose exec redis redis-cli ping
```

## Test

```bash
docker compose exec api pytest          # หรือ pytest ใน venv
```
มี contract test ฝั่ง frontend ด้วย (api container mount frontend/src แบบ read-only)

## ปุ่มฉุกเฉิน (ผ่าน `/admin/config` — มีผล 5 วิ ไม่ต้อง deploy)

- `maintenance_mode=true` → ปิดทุกอย่าง (503)
- `read_only_mode=true` → อ่านได้ เขียนไม่ได้ (หยุดเลือดตอนมีปัญหา)
- `features.{voting,wheel,ig_submission,checkin,quests}=false` → ปิดทีละฟีเจอร์
- `TOKEN_VERSION` bump → ล็อกเอาท์ทุกคนทันที (กดใน .env แล้ว `up -d --force-recreate`)

## เริ่มต้นแก้โค้ด — อ่านอะไรก่อน

1. [16-features.md](16-features.md) — ฟีเจอร์ที่จะแก้
2. [17-api-endpoints.md](17-api-endpoints.md) — endpoint ที่เกี่ยวข้อง
3. [02-database-schema.md](02-database-schema.md) — collection/index
4. `app/routers/<feature>.py` — endpoint
5. `app/services/<feature>.py` — business logic
6. `app/core/config.py` — ทุก setting
