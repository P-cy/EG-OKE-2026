# 01 — System Architecture

## 1. ภาพรวม

```
                        ┌─────────────────────────┐
   ผู้ใช้ 5,000 คน ─────►│  Cloudflare (Free)      │  DNS + CDN + WAF + DDoS
   จอแสดงผล 5-10 จอ     │  TTL 60s, proxied       │  cache static + live.json
   Staff scanner 4-6    └───────────┬─────────────┘
                                    │ HTTPS
                        ┌───────────▼─────────────┐
                        │  Nginx (app-1)          │
                        │  · TLS termination      │
                        │  · limit_req (burst)    │  ◄── ด่านแรกที่กัน burst
                        │  · proxy_cache 1s       │      (micro-cache)
                        │  · static file serving  │
                        └───────────┬─────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
     ┌────────▼────────┐  ┌─────────▼────────┐  ┌────────▼────────┐
     │ FastAPI api ×4  │  │ FastAPI ws ×2    │  │ Worker ×2       │
     │ (REST, stateless)│ │ (WebSocket only) │  │ (consume stream)│
     └────────┬────────┘  └─────────┬────────┘  └────────┬────────┘
              │                     │                     │
              └──────────┬──────────┴─────────────────────┘
                         │
        ┌────────────────▼─────────────────┐
        │  Redis 7  (app-1, replica app-2) │
        │  · dedupe / idempotency          │
        │  · vote counters (INCR)          │
        │  · leaderboard (ZSET)            │
        │  · rate limit (token bucket)     │
        │  · Streams = durable write queue │
        │  · Pub/Sub = WS fanout           │
        │  · live snapshot cache           │
        └────────────────┬─────────────────┘
                         │ (async drain, ไม่อยู่ใน request path)
        ┌────────────────▼─────────────────┐
        │  MongoDB Replica Set (PSA)       │
        │  P: app-1   S: app-2   A: ops    │
        │  = source of truth + audit trail │
        └──────────────────────────────────┘
```

## 2. แยกโปรเซสตามหน้าที่ (สำคัญมาก)

อย่ารวม REST + WebSocket + background worker ไว้ใน process เดียว เพราะ:

| Process | ทำไมต้องแยก |
|---|---|
| `api` (uvicorn ×4 workers) | stateless, restart ได้ตลอด, scale ตาม CPU |
| `ws` (uvicorn ×2 workers) | ถือ connection ยาว — ถ้า restart รวมกับ api ทุกคนหลุดพร้อมกัน |
| `worker` (×2) | drain Redis Stream → Mongo. ถ้าช้าหรือค้าง ต้องไม่กระทบ API |
| `broadcaster` (×1, singleton) | สร้าง snapshot ทุก 1 วิ + publish. ต้องมีตัวเดียวเท่านั้น |
| `scheduler` (×1, singleton) | ปิด/เปิดรอบโหวต, snapshot backup, cleanup |

`broadcaster` และ `scheduler` ใช้ Redis lock (`SET NX PX`) กันไม่ให้รันซ้อน

## 3. Write path: หัวใจของการไม่ล่ม

### ❌ แบบที่ทำให้ล่ม
```
POST /votes → validate → mongo.insert_one() → mongo.update_one(counter)
```
Mongo write = 5–20ms + lock contention ที่ document counter → 2,000 คนกดพร้อมกัน = write conflict, connection pool หมด, timeout ลามทั้งระบบ

### ✅ แบบที่ใช้
```
POST /votes
  ├─ 1. verify JWT                        (~0.1ms, ไม่แตะ DB)
  ├─ 2. rate limit  (Redis token bucket)  (~0.3ms)
  ├─ 3. EVAL vote.lua  ─────────────────► atomic ใน Redis เดียว:
  │        · SET NX  vote:{round}:{uid}      กันโหวตซ้ำ
  │        · HINCRBY tally:{round} {artist}  นับคะแนน
  │        · ZINCRBY lb:{round} 1 {artist}   leaderboard
  │        · XADD    stream:votes            คิวถาวร
  └─ 4. return 202 Accepted                (~1ms total)

Background worker (แยกโปรเซส)
  └─ XREADGROUP → bulk_write ลง Mongo ทีละ 500 → XACK
```

**ผลลัพธ์:** vote endpoint ใช้ Redis op เดียว (Lua script = atomic, 1 round-trip)
วัดได้จริง ~0.15ms ที่ Redis → **หนึ่ง instance รับได้ >20,000 vote/s**

**และที่สำคัญกว่า: Mongo ล่ม → คนยังโหวตได้** stream ค้างไว้ พอ Mongo กลับมา worker ก็ drain ต่อ ไม่มีโหวตหาย

### Lua script (ตัวจริงอยู่ใน `backend/app/scripts/vote.lua`)
```lua
-- KEYS[1]=dedupe  KEYS[2]=tally  KEYS[3]=zset  KEYS[4]=stream
-- ARGV[1]=user_id ARGV[2]=artist_id ARGV[3]=round_id ARGV[4]=ttl ARGV[5]=ts
if redis.call('EXISTS', KEYS[1]) == 1 then
  return {0, redis.call('GET', KEYS[1])}      -- โหวตไปแล้ว คืนตัวเดิม (idempotent)
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[4])
redis.call('HINCRBY', KEYS[2], ARGV[2], 1)
redis.call('ZINCRBY', KEYS[3], 1, ARGV[2])
redis.call('XADD', KEYS[4], '*', 'u', ARGV[1], 'a', ARGV[2], 'r', ARGV[3], 't', ARGV[5])
return {1, ARGV[2]}
```

## 4. Read path: ทำให้ 2,000 คนดูผลสดพร้อมกันแล้วไม่ล่ม

แยกผู้อ่านเป็น 2 ชนชั้น เพราะความต้องการต่างกันมาก:

| ผู้ใช้ | จำนวน | วิธี | เหตุผล |
|---|---|---|---|
| **จอแสดงผลหน้างาน** | 5–10 | WebSocket, push ทุก 250ms | ต้องเนียน ต้องทันที ต้อง sync วงล้อ |
| **มือถือผู้เข้าร่วม** | ~2,000 | HTTP GET `/live/snapshot` ทุก 3 วิ | ต้องถูกและทนทาน |

**ทำไมมือถือไม่ใช้ WebSocket:** 2,000 WS connection = 2,000 file descriptor + memory + ถ้า WiFi งานสั่นทีเดียว reconnect storm พร้อมกัน = ระบบตาย ส่วน HTTP polling ถ้าพลาดรอบนึงก็แค่ช้าไป 3 วิ ไม่มีใครตาย

**และ polling ไม่แพงเลย เพราะ Nginx micro-cache:**
```nginx
proxy_cache_valid 200 1s;
proxy_cache_lock on;              # 2,000 req พร้อมกัน → upstream เห็นแค่ 1
proxy_cache_use_stale updating error timeout;  # backend ล่ม → เสิร์ฟของเก่า
```
2,000 clients ÷ 3 วิ = 667 rps มาถึง Nginx แต่ **ถึง FastAPI แค่ 1 rps** และ Nginx เสิร์ฟจาก memory ได้ >30,000 rps

เติม Cloudflare `Cache-Control: public, max-age=2, stale-while-revalidate=10` อีกชั้น → ส่วนใหญ่ไม่ถึง server เราด้วยซ้ำ

## 5. กลยุทธ์กัน burst 5 ชั้น

| ชั้น | เครื่องมือ | กันอะไร |
|---|---|---|
| 1 | Cloudflare cache + Bot Fight | traffic ที่ไม่ต้องถึงเราเลย |
| 2 | Nginx `limit_req zone=api burst=20 nodelay` | flood ต่อ IP |
| 3 | Nginx `proxy_cache_lock` | thundering herd ตอน cache miss |
| 4 | App: Redis token bucket ต่อ user | คนเดียวกดรัวๆ |
| 5 | App: circuit breaker → degraded mode | Mongo ช้า → ตัดเป็น Redis-only ชั่วคราว |

## 6. Degraded mode — สิ่งที่ทีมส่วนใหญ่ลืม

ต้องนิยามล่วงหน้าว่าถ้าอะไรพัง ระบบยังทำอะไรได้บ้าง:

| อะไรพัง | ยังทำงาน | หยุด | ผู้ใช้เห็นอะไร |
|---|---|---|---|
| Mongo primary ล่ม | โหวต, เช็คอิน, ดูผลสด, วงล้อ | login ใหม่, แก้โปรไฟล์, อนุมัติ IG | banner "ระบบกำลังกู้คืน บางฟีเจอร์ปิดชั่วคราว" |
| Redis ล่ม | ❌ เกือบทุกอย่าง | — | **นี่คือ single point of failure → ต้องมี Sentinel + AOF** |
| app-1 ทั้งเครื่องล่ม | ทุกอย่าง (หลัง failover 2–5 นาที) | — | ช่วง failover ขึ้นหน้า maintenance ที่ Cloudflare |
| อินเทอร์เน็ตงานล่ม | สแกน QR แบบ offline | ทุกอย่างที่ต้อง network | scanner ใช้ local queue |

**QR offline mode สำคัญที่สุด** เพราะ WiFi ในงานอีเวนต์พังบ่อยที่สุด → ดู `06-security.md`

## 7. เหตุผลของ tech choice

| เลือก | เพราะ | ที่ไม่เลือกและทำไม |
|---|---|---|
| FastAPI + uvicorn | async native เหมาะกับ I/O-bound (Redis/Mongo) มาก, OpenAPI ฟรี, Pydantic validate ให้ | Django/Flask sync → ต้องใช้ thread pool เปลือง |
| MongoDB | ตามที่ทีมเลือก + schema ยืดหยุ่นดีสำหรับ event ที่กติกาเปลี่ยนก่อนงาน 2 วัน | — |
| Redis Streams | มี consumer group + ack + replay ในตัว ไม่ต้องลง RabbitMQ/Kafka เพิ่ม | Celery + broker = อีก 2 service ที่ต้องดูแล |
| Docker Compose | ทีมนักศึกษา 5–10 คน, deploy 3 เครื่อง — k8s คือหนี้ทางเทคนิค | Kubernetes = ops burden เกินไป |
| Cloudflare Free | CDN + DDoS + WAF + DNS failover ฟรี | ไม่มีเหตุผลไม่ใช้ |

## 8. เพดานความสามารถ (คำนวณ)

Contabo Cloud VPS 30 = 8 vCPU / 24 GB RAM

| Endpoint type | rps ต่อ worker | 4 workers | หมายเหตุ |
|---|---|---|---|
| `/live/snapshot` (Nginx cache) | — | **>30,000** | ไม่ถึง Python เลย |
| `/votes` (Redis Lua เท่านั้น) | ~2,500 | **~10,000** | JWT verify คือคอขวด ไม่ใช่ Redis |
| `/checkin` (Redis + audit) | ~2,000 | ~8,000 | |
| `/me/profile` (Mongo read, cached) | ~1,200 | ~4,800 | cache hit 95% |
| `/auth/google/callback` (Mongo write) | ~250 | ~1,000 | ช้าสุด แต่เกิดครั้งเดียวต่อคน |

เป้าหมาย peak = 1,500 rps → **headroom ประมาณ 3–6 เท่า** เพียงพอมาก
เครื่องที่ 2 มีไว้เพื่อ HA ไม่ใช่เพื่อ capacity

> ตัวเลขนี้เป็นการประมาณจากลักษณะงาน (async I/O-bound, payload เล็ก) — **ต้อง validate ด้วย k6 load test ก่อนงานจริง** ดู `08-workplan.md` §Load Testing
