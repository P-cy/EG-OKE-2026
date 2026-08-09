# 04 — Realtime System

ฟีเจอร์ที่ต้อง realtime: **ผลโหวตสด · วงล้อสุ่มรางวัล · Leaderboard · สถานะเช็คอิน**

## 1. หลักการ: แยกผู้ชมเป็น 2 ชนชั้น

| | จอแสดงผล (Display) | มือถือผู้เข้าร่วม |
|---|---|---|
| จำนวน | 5–10 | ~2,000 |
| ช่องทาง | **WebSocket** | **HTTP polling 3 วิ** |
| ความหน่วง | < 250ms | < 3 วิ |
| ถ้าหลุด | ต้อง reconnect ทันที + มีเสียงเตือน | ไม่มีใครสังเกต |
| Auth | display token (long-lived, ผูก device) | access token ปกติ หรือไม่ต้องมี |

**เหตุผลที่มือถือไม่ใช้ WebSocket:**
- 2,000 persistent connection บน WiFi งานอีเวนต์ = reconnect storm เมื่อ AP สั่น ทุกคน reconnect พร้อมกัน → ระบบตายรอบสอง
- มือถือล็อกหน้าจอ = WS ตาย = ต้อง reconnect ทุกครั้งที่หยิบขึ้นมาดู
- HTTP polling ถูก, cache ได้, stateless, ล้มเหลวแบบไม่เจ็บ

ยกเว้น: ถ้าทีมอยากได้ real-time บนมือถือจริงๆ ใช้ **SSE (`text/event-stream`)** ได้ — reconnect อัตโนมัติในตัว ถูกกว่า WS แต่ยังต้องถือ connection อยู่ดี → แนะนำใช้เฉพาะหน้า "วงล้อกำลังหมุน" เท่านั้น แล้วปิดเมื่อออกจากหน้า

## 2. Snapshot broadcaster (singleton process)

```python
# ทำงานทุก 1 วินาที
async def build_snapshot():
    seq = await r.incr("live:seq")
    tally = await r.hgetall(f"tally:{active_round}")
    top_p = await r.zrevrange("lb:points", 0, 9, withscores=True)
    top_ig = await r.zrevrange("lb:ig", 0, 9, withscores=True)
    stats = await r.hgetall("stats:checkin")

    snap = {...}
    await r.set("live:snapshot", json.dumps(snap), ex=30)   # ★ ex=30 = ถ้า broadcaster ตาย
                                                            #   ข้อมูลจะ stale ไม่เกิน 30 วิ แล้วหาย
    await r.publish("live:events", json.dumps({"type": "snapshot", "data": snap}))
```

- **ต้องมีตัวเดียว** ป้องกันด้วย Redis lock: `SET live:broadcaster:lock <id> NX PX 3000` renew ทุก 1 วิ
- API endpoint `GET /live/snapshot` แค่ `GET live:snapshot` แล้วคืนดิบๆ — **ไม่คำนวณอะไรเลย**
- ทุก 10 วินาที เขียน `vote_tallies` ลง Mongo ด้วย เผื่อ Redis ตาย

## 3. WebSocket protocol

**Connect:** `wss://api.egoke2026.example/v1/live/ws?token=<display_token>`

### Server → Client
```jsonc
{ "type": "hello",     "seq": 84213, "server_time": "...", "heartbeat_interval": 20 }
{ "type": "snapshot",  "seq": 84214, "data": { /* เหมือน GET /live/snapshot */ } }
{ "type": "vote.tick", "seq": 84215, "round_key": "d2-main",
                       "tally": { "<artist_id>": 1821 } }        // delta เล็กๆ ทุก 250ms
{ "type": "checkin.tick", "count_today": 2432, "rate_per_min": 18 }
{ "type": "wheel.arm",    "wheel_key": "main-wheel", "starts_in_ms": 3000 }
{ "type": "wheel.spin",   "spin_id": "...", "segment_index": 4,
                          "duration_ms": 6000, "easing": "cubicOut" }
{ "type": "wheel.result", "segment_index": 4, "label": "+50 คะแนน",
                          "winner": { "display_name": "PP", "avatar_url": "..." } }
{ "type": "announce",  "text": "...", "level": "warn" }
{ "type": "ping" }
```

### Client → Server
```jsonc
{ "type": "subscribe", "channels": ["vote:d2-main", "wheel:main-wheel", "checkin"] }
{ "type": "pong" }
{ "type": "resume", "last_seq": 84210 }   // reconnect แล้วขอของที่พลาด (server เก็บ 200 event ล่าสุด)
```

### Fanout ข้าม worker ด้วย Redis Pub/Sub
```
broadcaster ──PUBLISH live:events──► Redis
                                       │
                    ┌──────────────────┼──────────────────┐
                 ws-worker-1       ws-worker-2        ws-worker-N
                    │                  │                   │
              conn A,B,C          conn D,E,F          conn G,H
```
แต่ละ ws-worker `SUBSCRIBE live:events` ครั้งเดียว แล้ว fanout ให้ connection ในตัวเอง
→ Redis เห็นแค่ 1 publish ไม่ว่าจะมีกี่ worker

### Backpressure (สำคัญ)
ถ้า client ช้า (จอ Raspberry Pi เก่าๆ) queue จะบวม → กิน RAM จนโปรเซสตาย
```python
if conn.queue.qsize() > 50:
    await conn.close(code=1013, reason="slow_consumer")   # ตัดทิ้ง ให้มันต่อใหม่
```
`vote.tick` เป็น **state ไม่ใช่ event** — ส่งค่าล่าสุดเสมอ ถ้า client พลาดไป 5 tick ก็ไม่เป็นไร ให้ทิ้ง tick เก่าใน queue ได้เลย (coalesce)

### Heartbeat
- Server ส่ง `ping` ทุก 20 วิ · ถ้าไม่มี `pong` ใน 30 วิ → ปิด
- Client ไม่ได้รับอะไรเลย 30 วิ → reconnect ด้วย exponential backoff + jitter (`1s, 2s, 4s, 8s, max 30s` ±30%)
- **jitter บังคับ** ไม่งั้น 10 จอ reconnect พร้อมกันเป๊ะ ตอน server เพิ่ง restart

## 4. วงล้อสุ่มรางวัล — Provably Fair

### ปัญหาที่ต้องแก้
1. คนจะกล่าวหาว่าโกง → ต้องพิสูจน์ได้
2. เปิด DevTools แล้วแก้ผลไม่ได้ → server ต้องเป็นคนตัดสิน
3. จอบนเวทีกับมือถือต้องเห็นผลเดียวกัน → sync

### Commit–Reveal
```
ก่อนงาน:  server_seed = secrets.token_hex(32)         (เก็บลับ, encrypt at rest)
          commit_hash = sha256(server_seed)
          → ประกาศ commit_hash ในหน้าเว็บ + โพสต์ IG ทางการ (timestamp พิสูจน์ได้)

ตอนหมุน:  raw   = HMAC_SHA256(key=server_seed, msg=f"{client_seed}:{nonce}")
          n     = int(raw[:8], 16)                    # 32 bit แรก
          idx   = n % total_weight
          หา segment จาก cumulative weight

หลังงาน:  เปิดเผย server_seed → ใครก็ตรวจได้ว่า sha256(server_seed) == commit_hash
          และคำนวณผลทุกใบซ้ำได้เอง
```

### Sequence การหมุนบนเวที
```
Admin กด "หมุน"
   │
   ├─► POST /admin/wheel/main-wheel/trigger
   │     ├─ server คำนวณผลทันที (ล็อกไว้แล้ว)
   │     ├─ หัก stock / บันทึก wheel_spins
   │     └─ PUBLISH:
   │
   ├─ t=0ms     wheel.arm   { starts_in_ms: 3000 }   → จอเริ่มนับถอยหลัง 3-2-1
   ├─ t=3000ms  wheel.spin  { segment_index: 4, duration_ms: 6000 }
   │              → จอหมุน 6 วิ ให้หยุดตรง index 4
   ├─ t=9000ms  wheel.result { winner: {...} }       → จอโชว์ผู้ชนะ + confetti
```
`wheel.arm` มาก่อน 3 วินาที **เพื่อชดเชย network jitter** จอทุกตัวได้รับข้อความในช่วง 20–300ms แต่ทุกตัวเริ่มหมุนที่ `server_time + 3000ms` พร้อมกันเป๊ะ

Frontend คำนวณองศา:
```js
const seg = 360 / segments.length;
const targetDeg = 360 * 8                        // หมุน 8 รอบให้ดูสวย
                + (360 - segmentIndex * seg)     // ให้ช่องเป้าหมายมาอยู่ตรงเข็ม
                - seg / 2;                       // กึ่งกลางช่อง
el.style.transition = `transform 6s cubic-bezier(.17,.67,.24,1)`;
el.style.transform  = `rotate(${targetDeg}deg)`;
```

### กันเคสน่าอาย
| เคส | วิธีกัน |
|---|---|
| จอค้างกลางหมุน | `wheel.result` ส่งซ้ำ 3 ครั้งห่างกัน 1 วิ + จอมีปุ่ม "sync ใหม่" |
| หมุนแล้วของหมด | `$inc remaining:-1` แบบมีเงื่อนไข → fail ก็ตกเป็น "ไม่ถูกรางวัล" |
| Admin กดสองครั้ง | Redis lock `wheel:trigger:{key}` 15 วิ + idempotency key |
| เน็ตบนเวทีล่ม | จอมี local fallback: ถ้า WS หลุด >5 วิ ให้ poll `/live/snapshot` แทน |

## 5. Leaderboard

Redis Sorted Set — อ่าน rank เป็น O(log N) ไม่ต้องแตะ Mongo เลย
```
ZINCRBY lb:points 50 <user_id>
ZREVRANGE lb:points 0 9 WITHSCORES     → top 10
ZREVRANK  lb:points <user_id>          → อันดับของฉัน
```
- rebuild จาก `point_transactions` ได้เสมอถ้า Redis หาย
- **แคชชื่อ+รูป** ไว้ใน Redis hash `u:meta:{id}` (TTL 1 ชม.) ไม่งั้น top-10 = 10 Mongo query ทุกวินาที
- `lb:ig` แยก ZSET ต่างหาก นับจำนวนโพสต์ที่อนุมัติ

## 6. สถานะเช็คอินหน้างาน

```
HINCRBY stats:checkin today 1
HINCRBY stats:checkin gate:GATE-A 1
LPUSH   stats:checkin:recent <json>  ; LTRIM stats:checkin:recent 0 19   # feed 20 คนล่าสุด
```
จอ staff เห็น: จำนวนวันนี้ · อัตราต่อนาที · แยกตามประตู · หน้าคนที่เพิ่งเข้า 20 คนล่าสุด (ดูดี + ช่วยจับคนสแกนซ้ำ)

`rate_per_min` คำนวณจาก sliding window: `ZADD stats:checkin:ts <ts> <id>` + `ZCOUNT` ช่วง 60 วิล่าสุด (ZREMRANGEBYSCORE ตัดของเก่าทิ้ง)

## 7. Client polling ที่ถูกต้อง

```js
let seq = 0, delay = 3000;

async function poll() {
  try {
    const r = await fetch('/v1/live/snapshot', { headers: { 'If-None-Match': etag } });
    if (r.status === 304) { delay = 3000; return; }      // ไม่มีอะไรใหม่ ประหยัด bandwidth
    const d = await r.json();
    if (d.seq > seq) { seq = d.seq; render(d); }
    delay = 3000;
  } catch { delay = Math.min(delay * 2, 30000); }        // ★ backoff เมื่อ error
  finally { setTimeout(poll, delay + Math.random() * 500); }  // ★ jitter
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopPoll();                        // ★ ประหยัดแบตและ server
  else { poll(); }
});
```
สามอย่างที่ห้ามลืม: **backoff เมื่อ error · jitter · หยุดเมื่อแท็บถูกซ่อน**
ถ้าไม่มี 3 อย่างนี้ ตอน server ล่มแล้ว 2,000 client จะยิงรัวพร้อมกัน = ฟื้นไม่ขึ้น
