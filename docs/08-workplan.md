# 08 — Work Plan

## 1. แตกงานจาก README เป็น Module

README บอกแค่ "ทีมทำอะไร" — นี่คือการแตกเป็นชิ้นงานที่มอบหมายได้จริง

| # | Module | ที่มาจาก README | เจ้าของ | ขนาด |
|---|---|---|---|---|
| **B1** | Auth & Identity (Google OAuth, JWT, roles) | "เข้าสู่ระบบผ่านอีเมลมหาวิทยาลัย" | BE | L |
| **B2** | User Profile & Onboarding | "ออกแบบฐานข้อมูลสำหรับข้อมูลผู้ใช้" | BE | M |
| **B3** | Ticket & QR (ออกบัตร, HMAC, TOTP) | "บัตรเข้างาน", "ระบบ QR Code" | BE | L |
| **B4** | Check-in API + offline sync | "ตรวจสอบสิทธิ์เข้างาน" | BE | L |
| **B5** | Points Ledger | "คะแนน" | BE | M |
| **B6** | Voting Engine (Redis Lua + worker) | "การโหวต" | BE | **XL** |
| **B7** | Instagram Submission + Moderation | "คำขอศิลปิน", "ส่ง Instagram" | BE | M |
| **B8** | Wheel Engine (provably fair) | "วงล้อสุ่มรางวัล" | BE | L |
| **B9** | Realtime (WS + broadcaster + SSE) | "จอแสดงกิจกรรม" | BE | **XL** |
| **B10** | Admin API + audit log | "หน้าควบคุมของเจ้าหน้าที่", "ระบบ Admin" | BE | L |
| **B11** | Infra, Deploy, Backup, DR | "ระบบสำรองข้อมูล และ Backup Server" | DevOps | **XL** |
| **B12** | Observability + Load test | (ไม่มีใน README — **ต้องเพิ่ม**) | DevOps | M |
| **F1** | Design system + responsive shell | "รองรับโทรศัพท์ แท็บเล็ต คอมพิวเตอร์" | FE | L |
| **F2** | Login / Home / Profile | "หน้า Login, Home และ Profile" | FE | M |
| **F3** | Voting UI | "โหวตศิลปิน" | FE | M |
| **F4** | IG submission + สถานะคำขอ | "ส่ง Instagram", "ตรวจสอบสถานะคำขอ" | FE | M |
| **F5** | Points / Leaderboard | "ดูคะแนนสะสม" | FE | M |
| **F6** | QR wallet (หน้าแสดงบัตร) | "QR Code" | FE | S |
| **F7** | Wheel UI (animation sync) | "หน้าวงล้อ" | FE | L |
| **F8** | Display screens (จอหน้างาน) | "จอแสดงกิจกรรม" | FE | L |
| **F9** | Scanner PWA (offline-first) | "ตรวจสอบ QR Code หน้างาน" | FE | **XL** |
| **F10** | Admin dashboard UI | "หน้าควบคุมของเจ้าหน้าที่" | FE | L |
| **O1** | Network plan + 4G backup | "อินเทอร์เน็ต", "แก้ไขปัญหาฉุกเฉิน" | Onsite | M |
| **O2** | Device setup + ซ้อมหน้างาน | "ติดตั้งและตรวจสอบคอมพิวเตอร์" | Onsite | M |
| **O3** | Runbook + war room | "แก้ไขปัญหาฉุกเฉินหน้างาน" | Onsite + BE | M |

**สิ่งที่ README ขาดและต้องเพิ่ม:** Load testing, Observability, Rate limiting, PDPA compliance, Runbook ที่ซ้อมจริง

---

## 2. Timeline 8 สัปดาห์

```
W1  ████ Foundation
W2  ████ Auth + Core data
W3  ████ Ticket / QR / Check-in
W4  ████ Voting + Points
W5  ████ IG + Wheel + Realtime
W6  ████ Admin + Display
W7  ████ ⚠️ HARDENING + LOAD TEST  ← ห้ามข้าม
W8  ████ ซ้อมเสมือนจริง + Freeze
```

### W1 — Foundation
| งาน | ใคร | Done เมื่อ |
|---|---|---|
| Repo, CI, lint, pre-commit | DevOps | push แล้ว CI เขียว |
| Docker Compose local (mongo+redis+api) | DevOps | `docker compose up` ขึ้นครบ |
| สั่งซื้อ VPS + ตั้งค่าเบื้องต้น | DevOps | ssh เข้าได้ทั้ง 3 เครื่อง |
| FastAPI skeleton + `/healthz` | BE | curl ได้ |
| API contract ตกลงกับ FE (freeze) | BE+FE | OpenAPI committed |
| Design system + Figma | FE | component หลักครบ |

> ⚠️ **สั่ง VPS สัปดาห์แรกเลย** — Contabo ใช้เวลา provision หลายชั่วโมงถึงหลายวัน

### W2 — Auth + Core data
- B1 Google OAuth end-to-end (login จริงด้วยอีเมลมหิดลได้)
- B2 user model + onboarding
- Index script + seed data (users ปลอม 5,000 คน สำหรับเทสต์)
- F1 shell + F2 login page
- **Gate:** login ด้วย gmail.com ต้องถูกปฏิเสธ

### W3 — Ticket / QR / Check-in
- B3 ออกบัตร + HMAC payload + TOTP
- B4 `/checkin` + `/checkin/batch` + idempotency
- F6 QR wallet, F9 Scanner PWA (offline queue)
- **Gate:** สแกน QR เดิม 2 ครั้ง → ครั้งที่ 2 = `duplicate`
- **Gate:** ปิด WiFi แล้วสแกน 20 ใบ → เปิด WiFi → sync ครบ 20

### W4 — Voting + Points
- B6 Lua script + stream worker + tally
- B5 ledger + reconcile job
- F3 voting UI, F5 leaderboard
- **Gate:** ยิง 10,000 vote พร้อมกันจาก 1,000 user → นับได้ 1,000 พอดี ไม่ขาดไม่เกิน

### W5 — IG + Wheel + Realtime
- B7 submission + moderation queue
- B8 wheel engine + commit-reveal
- B9 broadcaster + WS + snapshot
- F4, F7 wheel animation
- **Gate:** วงล้อ 3 จอหมุนพร้อมกัน หยุดช่องเดียวกัน ต่างกัน < 300ms
- **Gate:** ตรวจสอบ `sha256(server_seed) == commit_hash` ผ่าน

### W6 — Admin + Display
- B10 admin API ครบ + audit log middleware
- F10 admin dashboard, F8 display screens
- B12 Prometheus + Grafana + alert
- **Gate:** ทุก action ใน `/admin` มี audit log record

### W7 — ⚠️ Hardening + Load Test (สัปดาห์ที่สำคัญที่สุด)
| งาน | เกณฑ์ผ่าน |
|---|---|
| k6 load test เต็มรูปแบบ | ดู §3 |
| Security checklist ทั้งหมด | `06-security.md` §11 ผ่านครบ |
| ซ้อม failover app-1 → app-2 | **< 5 นาที** |
| ทดสอบ restore backup | document count ตรง 100% |
| Chaos test: kill mongo/redis ระหว่างมี traffic | ไม่มี vote หาย |
| Deploy production จริง + smoke test | ผ่าน |

> **ถ้าตารางเลื่อน ให้ตัดฟีเจอร์ ห้ามตัดสัปดาห์นี้**

### W8 — ซ้อมเสมือนจริง + Freeze
- **Dry run เต็มรูปแบบ 1 วัน**: staff 20 คน + volunteer 100 คน สแกนจริง โหวตจริง หมุนจริง
- แก้บั๊กที่เจอจาก dry run (เจอเยอะแน่นอน)
- **Code freeze 48 ชม. ก่อนงาน** — หลังจากนี้แก้ได้เฉพาะ P0
- พิมพ์ runbook ออกกระดาษ แจกทีม onsite
- Brief ทีมทุกคน: ใครโทรหาใคร ปัญหาแบบไหน

---

## 3. Load Testing Plan (k6)

```js
// tests/load/event-day.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    // สถานการณ์ปกติตลอดวัน
    baseline: {
      executor: 'constant-arrival-rate',
      rate: 50, timeUnit: '1s', duration: '10m',
      preAllocatedVUs: 100,
    },
    // ★ สถานการณ์จริงที่ทำให้ล่ม: MC ประกาศเปิดโหวต
    vote_spike: {
      executor: 'ramping-arrival-rate',
      startTime: '5m',
      startRate: 50, timeUnit: '1s',
      preAllocatedVUs: 2000, maxVUs: 4000,
      stages: [
        { target: 1500, duration: '20s' },   // พุ่งใน 20 วิ
        { target: 1500, duration: '60s' },   // ค้าง 1 นาที
        { target: 50,   duration: '30s' },   // ลดลง
      ],
    },
    // 2,000 มือถือ poll พร้อมกัน
    live_poll: {
      executor: 'constant-vus',
      vus: 2000, duration: '10m',
    },
  },
  thresholds: {
    'http_req_duration{scenario:vote_spike}': ['p(99)<500'],
    'http_req_duration{scenario:live_poll}':  ['p(99)<200'],
    'http_req_failed': ['rate<0.005'],       // ★ ล้มเหลวได้ไม่เกิน 0.5%
  },
};
```

### เกณฑ์ผ่าน (ต้องผ่านทุกข้อ)
| Metric | เกณฑ์ |
|---|---|
| p99 latency `/votes` ตอน spike | < 500 ms |
| p99 latency `/live/snapshot` | < 200 ms |
| Error rate | < 0.5% |
| **จำนวนโหวตใน Mongo == จำนวน user ที่ยิง** | 100% ตรง |
| Nginx cache hit ratio บน `/live/*` | > 95% |
| CPU app-1 ตอน peak | < 70% |
| Redis memory | < 50% |
| Vote stream lag หลัง spike จบ 60 วิ | = 0 |

### สิ่งที่ต้องทดสอบด้วยและคนมักลืม
- [ ] ทดสอบจากเครื่องนอก datacenter (ไม่ใช่จาก localhost) — จะได้เห็น network latency จริง
- [ ] ทดสอบ **หลัง** เปิด Cloudflare (บาง rule อาจ block k6)
- [ ] ทดสอบตอน Mongo ล่ม → vote ต้องยังผ่าน (นี่คือจุดขายของ design นี้)
- [ ] ทดสอบ WebSocket 10 จอ ค้างไว้ 3 ชั่วโมง → ไม่มี memory leak
- [ ] ทดสอบ reconnect storm: ตัด WS ทั้งหมดพร้อมกันแล้วดูว่าฟื้นไหม

---

## 4. Definition of Done (ทุก module)

- [ ] มี unit test สำหรับ business logic (โดยเฉพาะ ledger, wheel, dedupe)
- [ ] มี integration test ที่แตะ Mongo/Redis จริง
- [ ] endpoint ทุกตัวมี OpenAPI description + example
- [ ] error case คืน error code ตามสเปก ไม่ใช่ 500
- [ ] write endpoint ทุกตัวรองรับ idempotency (ยิง 2 ครั้ง = ผลเหมือน 1 ครั้ง)
- [ ] มี metric อย่างน้อย 1 ตัว
- [ ] log เป็น structured JSON มี `request_id`
- [ ] FE ต่อได้จริงและ demo ให้ทีมดูแล้ว

---

## 5. Runbook หน้างาน (พิมพ์ออกกระดาษ)

### ตารางเวรและช่องทางติดต่อ
| กะ | เวลา | Backend on-call | Onsite lead |
|---|---|---|---|
| เช้า | 08:00–14:00 | ___ | ___ |
| บ่าย | 14:00–20:00 | ___ | ___ |
| ดึก | 20:00–02:00 | ___ | ___ |

### ปัญหาที่เจอบ่อยที่สุดและวิธีแก้ทันที

| อาการ | ตรวจก่อน | แก้ยังไง |
|---|---|---|
| เว็บช้าทั้งระบบ | Grafana: CPU / p99 / Mongo pool | `docker compose restart api` (ผู้ใช้ไม่รู้สึก มี graceful) |
| โหวตไม่ขึ้นบนจอ | `egoke_vote_stream_lag` | ถ้า lag สูง → restart worker; ถ้า 0 → ปัญหาที่ broadcaster |
| จอค้าง | WS connection count | รีเฟรชเบราว์เซอร์จอนั้น (F5) |
| Scanner สแกนไม่ผ่านทุกใบ | นาฬิกาเครื่อง scanner | ปิด `STRICT_QR_MODE` ผ่าน `/admin/config` |
| คนบ่นว่าเช็คอินแล้วแต่ระบบบอกยัง | `checkins` collection | ค้นด้วย `ticket_code` ดู result |
| คิวหน้าประตูยาว | จำนวน scanner ที่ active | เปิด `FAST_CHECKIN_MODE` (ข้าม TOTP) |
| ทุกอย่างพัง ไม่รู้สาเหตุ | — | `/admin/config` → `read_only_mode: true` → หายใจ → หาสาเหตุ |

### ปุ่มฉุกเฉิน (`PATCH /admin/config`)
```jsonc
{ "maintenance_mode": true }              // ปิดทั้งเว็บ ขึ้นหน้าแจ้ง
{ "read_only_mode": true }                // อ่านได้ เขียนไม่ได้ (กัน data corruption)
{ "features": { "voting": false } }       // ปิดเฉพาะโหวต
{ "announcement": { "text": "ระบบกำลังปรับปรุง กลับมาใน 5 นาที", "level": "warn" } }
```
มีผลภายใน 5 วินาที ไม่ต้อง deploy ไม่ต้อง restart

### เบอร์ที่ต้องมีในกระดาษ
- Contabo support: (จากหน้า dashboard)
- ผู้ดูแลเน็ตเวิร์กของคณะ: ___
- คนที่มี Cloudflare account: ___
- คนที่มี ssh key ของ production: ___ (ต้องมีอย่างน้อย 2 คน)

> **กฎข้อเดียวที่สำคัญที่สุด:** อย่าให้มีคนเดียวที่เข้า production ได้
> ถ้าคนนั้นแบตหมด/หลับ/ป่วย = จบเกม
