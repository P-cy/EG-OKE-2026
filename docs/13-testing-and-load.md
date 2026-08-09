# 13 — เทสต์ · CI · Load test

เอกสารนี้บอกว่า "ระบบถูกตรวจด้วยอะไรบ้าง" และ "รันเองยังไง"

---

## 1. รันเทสต์

### Backend (68 เทสต์)

```bash
cd backend
docker compose exec api python -m pytest tests/ -q
docker compose exec api ruff check app/ scripts/ tests/
```

| ไฟล์ | ดูแลอะไร |
|---|---|
| `tests/test_core_logic.py` | Lua ของโหวต/rate limit, QR signing, การจัดรูปแบบข้อมูล |
| `tests/test_checkin.py` | แยกประเภทรหัสที่สแกน (QR / รหัสบัตร / รหัสนักศึกษา), ข้อความที่ staff เห็น |
| `tests/test_coins.py` | หักเหรียญพร้อมกันหลาย request แล้วยอดต้องไม่ติดลบ |
| `tests/test_quests.py` | สแกนบูธรัวๆ ต้องจ่ายเหรียญครั้งเดียว |
| `tests/test_refunds.py` | เงินที่จ่ายแล้วไม่ได้ของ ต้องคืน (ปฏิเสธรูป IG / วงล้อ nonce ชน) |
| `tests/test_ratelimit_nat.py` | rate limit ต้องรอดจาก NAT ของงาน (ดูข้อ 4) |
| `tests/test_api_contracts.py` | ชื่อคีย์และ enum ระหว่าง backend กับ frontend ต้องตรงกัน |

`test_api_contracts.py` อ่านไฟล์ `frontend/src/lib/api.ts` จริงๆ
docker compose mount ให้แล้วที่ `/frontend_src` (read-only)
ถ้าไม่มี mount เทสต์ชุดนี้จะ **skip** ไม่ใช่ fail — CI มีขั้นตอนบังคับว่าห้าม skip

### Frontend (33 เทสต์)

```bash
cd frontend
npm test              # vitest run
npm run test:watch
npx tsc --noEmit
```

| ไฟล์ | ดูแลอะไร |
|---|---|
| `src/lib/format.test.ts` | การแปลงเวลาจาก server (บั๊ก 7 ชม. — ดูข้อ 4) |
| `src/lib/api.test.ts` | Idempotency-Key, error envelope, refresh token ตอน 401 |
| `src/components/IGSubmissionRow.test.tsx` | แต่ละแถวโชว์ข้อมูลของใบตัวเอง |

---

## 2. CI

`.github/workflows/ci.yml` — รันทุก push บน `main` และทุก PR

**backend job** — Mongo 7 + Redis 7 เป็น service container
`ruff check app/ scripts/ tests/` → `pytest -q` → ตรวจว่าเทสต์ contract ไม่ถูก skip

**frontend job** — Node 22
`tsc --noEmit` → `npm test` → `next build`

ตัวแปรที่ CI ตั้งให้: `MONGO_DB=egoke2026_test` (ต้องลงท้าย `_test` ไม่งั้น
`conftest.py` จะเติมให้เอง — เป็นด่านกันเผลอรันเทสต์ใส่ฐานจริง)

---

## 3. Load test

```bash
# เตรียม user ปลอมก่อน (ทำครั้งเดียว)
docker compose exec api python -m scripts.seed_dev --users 5000

docker compose exec api python -m scripts.loadtest all
docker compose exec api python -m scripts.loadtest snapshot --rps 650 --seconds 20
```

ยิงแบบ **open-loop** — ปล่อย request ตามตารางเวลา ไม่รอ response ก่อนยิงตัวถัดไป
(ถ้ารอ เวลา server ช้าลงโหลดจะลดตามเอง แล้วจะไม่มีวันเห็นจุดที่มันพัง)

### ผลที่วัดได้ (dev stack, uvicorn 1 worker + `--reload`)

| ฉาก | เป้า | ทำได้ | p50 | p95 | สำเร็จ |
|---|---|---|---|---|---|
| `GET /live/snapshot` | 650 rps | 650 | 2 ms | 3 ms | 100% |
| `POST /checkin` (8 จุดสแกน) | 30 rps | 30 | 11 ms | 19 ms | 100% |
| `POST /votes` | 100 rps | 100 | 3 ms | 4 ms | 100% (202) |
| `GET /live/ig-wall` | 5 rps | 5 | 12 ms | 17 ms | 100%, payload 1.2 KB |

เป้า 650 rps มาจาก 2,000 มือถือ poll ทุก 3 วิ (~667 rps)

ตัวเลข snapshot 650 rps ต้องยิงเดี่ยวถึงจะได้:

```bash
docker compose exec api python -m scripts.loadtest snapshot --rps 650 --seconds 15
```

โหมด `all` ตั้ง snapshot ไว้ 500 rps เพื่อให้ผ่านซ้ำได้ทุกครั้ง — ใช้เป็น smoke test
ไม่ใช่ตัววัดเพดาน

### อ่านผลยังไงให้ไม่หลอกตัวเอง

- ตัวยิงโหลดรันในคอนเทนเนอร์เดียวกับ server → แย่ง CPU กันเอง
  เกิน ~700 rps ตัวยิงจะเป็นคอขวดเอง (เห็นเป็น `PoolTimeout` ไม่ใช่ server พัง)
- dev stack ไม่มี Nginx micro-cache ซึ่งของจริงจะดูดโหลด `/live/*` ไปเกือบหมด
- production ใช้ gunicorn หลาย worker ไม่ใช่ `--reload` worker เดียว
- **ตัวเลขนี้ใช้หา "จุดที่พังก่อน" ไม่ใช่ใช้รับประกัน capacity**

---

## 4. บั๊กที่ load test เจอ (และแก้แล้ว)

### 4.1 Rate limit ต่อ IP จะฆ่าทุกคนพร้อมกันหลัง NAT

`/live/snapshot` ถูกจำกัด **120 ครั้ง/นาที ต่อ IP**
แต่ผู้เข้าร่วมทั้ง 5,000 คนอยู่บน WiFi มหาลัยเดียวกัน = ออกเน็ตด้วย IP เดียว

```
5,000 เครื่อง × 20 ครั้ง/นาที = 100,000 ครั้ง/นาที จาก IP เดียว
เพดาน 120/นาที → ทุกคนโดน 429 พร้อมกันภายในวินาทีแรกของงาน
```

คอมเมนต์เตือนเรื่องนี้อยู่บนหัวไฟล์ `ratelimit.py` มาตลอด แต่ scope `live` ไม่ได้ทำตาม

**แก้:** `ratelimit.check_public()` — มี token ให้นับต่อ user, ไม่มีค่อยตกไปนับต่อ IP
ด้วยเพดานที่สูงกว่ามาก (`live_anon` 3,000/นาที สำหรับจอใหญ่ + คนที่ยังไม่ login)
การเลือก bucket ไม่เช็ค denylist ตั้งใจ — เป็นการเลือกช่อง ไม่ใช่การ auth
ประหยัด Redis ไป 1 รอบบน endpoint ที่โดนหนักที่สุด

เทสต์: `tests/test_ratelimit_nat.py`

### 4.2 จอใหญ่โหลดรูปทั้งกองใหม่ทุก 10 วินาที

`/live/ig-wall` เคยแนบ base64 ของทุกใบมาในก้อน JSON
30 ใบ × ~1 MB = โหลดใหม่ทั้งหมดทุกครั้งที่ poll ตลอดงาน

**แก้:** ส่งเป็นลิงก์ `/ig/image/{id}` ที่ `Cache-Control: max-age=86400, immutable`
บวกกับหน้า `/ig` ย่อรูปให้เหลือด้านยาว 1440px ก่อนส่ง

วัดได้: payload 1.2 KB/ครั้ง — หลังรอบแรกจอแทบไม่ใช้ bandwidth เลย

---

## 5. เทสต์แบบไหนที่คุ้มที่สุดในโปรเจกต์นี้

บั๊กที่แพงที่สุดที่เจอ ไม่ใช่ logic ผิด แต่เป็นสองแบบนี้ ซึ่ง **ผ่าน type checker ทั้งคู่**:

1. **ชื่อคีย์ไม่ตรงกันข้ามฝั่ง** — `/me/submissions` คืน `submissions`
   แต่หน้า `/ig` อ่าน `.items` → กล่องสถานะขึ้นว่า "ยังไม่เคยส่ง" ตลอด ไม่มี error ให้เห็น

2. **ชนิดข้อมูลที่ serialize ไม่ได้** — `/admin/audit-logs` คืน `ObjectId` ดิบ
   แต่ app ใช้ `ORJSONResponse` → 500 ทุกครั้ง ไม่เคยใช้งานได้เลยตั้งแต่เขียนมา

`tests/test_api_contracts.py` คุมทั้งสองแบบ — เพิ่ม endpoint ใหม่แล้วควรเพิ่มเคสที่นี่ด้วย
