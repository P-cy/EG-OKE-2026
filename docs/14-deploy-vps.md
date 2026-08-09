# 14 — ขึ้น VPS เครื่องเดียว (คู่มือที่ใช้จริง)

> เอกสาร [05-infrastructure.md](05-infrastructure.md) เขียนไว้ตอนออกแบบ เป็นแผนสำหรับ
> 3 เครื่อง (app-1 / app-2 / ops) ซึ่ง**เกินความจำเป็นสำหรับงานนี้มาก**
> ไฟล์นี้คือของที่ทำจริงและทดสอบแล้ว — VPS เครื่องเดียวจบ

---

## 1. VPS เครื่องเดียวพอไหม

พอ และเป็นทางเลือกที่ถูกต้องสำหรับงานนี้

เหตุผล: งานนี้กินทรัพยากรน้อยกว่าที่คิดมาก เพราะของหนักถูกกันไว้หมดแล้ว

| ของหนัก | ถูกกันด้วยอะไร |
|---|---|
| คนหลายพัน poll `/live/*` พร้อมกัน | nginx micro-cache 1 วิ — backend เห็นแค่ ~1 request/วินาที |
| โหวตพุ่งพร้อมกันตอนประกาศ | เขียนลง Redis ผ่าน Lua (atomic) ตอบ 202 ทันที แล้ว worker ค่อยลง Mongo |
| จอใหญ่หลายจอ | broadcaster ตัวเดียวคำนวณ snapshot แล้ว push ผ่าน WS |
| รูป IG บนจอ | ส่งเป็นลิงก์ `/ig/image/{id}` ที่ cache 1 วัน ไม่ใช่ base64 ทั้งกอง |

### สเปกที่แนะนำ

| | ขั้นต่ำ | แนะนำ |
|---|---|---|
| vCPU | 2 | **4** |
| RAM | 4 GB | **8 GB** |
| Disk | 40 GB | **80 GB SSD** |
| ที่ตั้ง | — | **สิงคโปร์** (ping จากไทย ~30-50ms · ยุโรป ~180-250ms) |

ที่ตั้งสำคัญกว่าสเปก — 200ms ต่อ request ทำให้จังหวะสแกน QR หน้างานรู้สึกหน่วงชัดเจน

RAM 8 GB แบ่งประมาณนี้: Mongo 1-2 · Redis 0.5 · api (gunicorn 4 worker) 1.5 · ws/worker/broadcaster 1 · nginx 0.1 · frontend 0.3 · เหลือให้ OS page cache

> ถ้าเอา frontend ไปไว้ Vercel (ฟรี) VPS จะเหลือแค่ backend — 4 GB ก็พอ

---

## 2. MongoDB — ต้องกังวลอะไรบ้าง

### เก็บด้วยอะไร

Mongo 7 ในคอนเทนเนอร์บน VPS เครื่องเดียวกัน ใช้ storage engine **WiredTiger**
เก็บลง docker volume `mongo_data` ซึ่งอยู่บนดิสก์ของ VPS

**ไม่ได้ใช้ Atlas** และไม่แนะนำให้ย้ายไปด้วย:

| | self-host (ที่ใช้อยู่) | Atlas M0 (ฟรี) | Atlas M10 |
|---|---|---|---|
| ความจุ | เท่าดิสก์ VPS | **512 MB** | 10 GB |
| ราคา | รวมในค่า VPS | ฟรี | ~2,000 บาท/เดือน |
| ความหน่วง | ในเครื่องเดียวกัน (~0.1ms) | ข้ามเน็ตเวิร์ก | ข้ามเน็ตเวิร์ก |
| replica set | มีอยู่แล้ว (rs0) | มีให้ | มีให้ |

M0 512 MB ไม่พอถ้ามีคนส่งรูป IG เยอะ และการยิงข้ามเน็ตเวิร์กทุก query
จะเพิ่ม latency ให้ทุกการสแกน — งานนี้ไม่มีเหตุผลที่จะย้ายไป

### ใช้พื้นที่เท่าไหร่จริง

วัดจากข้อมูลจริงในเครื่อง dev แล้วคูณขึ้น:

| collection | วัดได้ | คาดการณ์ 5,000 คน / 3 วัน |
|---|---|---|
| checkins | 2,693 แถว = 1.5 MB | 15,000 แถว ≈ **8 MB** |
| users | — | 5,000 คน ≈ **10 MB** |
| coin_transactions | 0.5 KB/แถว | ~100,000 แถว ≈ **50 MB** |
| votes | — | ~15,000 แถว ≈ **8 MB** |
| audit_logs | 0.5 KB/แถว | ~50,000 แถว ≈ **25 MB** |
| **ig_submissions** | **9 รูป = 1.09 MB (~121 KB/รูป)** | **ตัวนี้คือตัวที่กินพื้นที่จริง** |

ทุกอย่างที่ไม่ใช่รูป IG รวมกันประมาณ **100 MB** — ไม่ต้องคิดเลย

**รูป IG เก็บเป็น base64 ในเอกสาร Mongo** (ไม่ได้แยกไปเก็บที่อื่น) เพดานต่อรูปคือ
`IMAGE_MAX = 1,400,000` ตัวอักษร ≈ 1.4 MB

เพดานจำนวน: `IG_SUBMISSIONS_PER_DAY=5` × 3 วัน × 5,000 คน = **75,000 รูป**
- ตามค่าเฉลี่ยที่วัดได้ (121 KB): **~9 GB**
- กรณีเลวร้ายสุด (ทุกคนอัดเต็มเพดาน): ~105 GB

ในทางปฏิบัติจะน้อยกว่านั้นมาก เพราะการส่งรูปขึ้นจอ**หัก 20 เหรียญต่อครั้ง**
และเหรียญมีจำกัด (เช็คอินได้ 10/วัน) — เศรษฐศาสตร์ในเกมเป็นตัวคุมอยู่แล้ว
ประมาณการจริง: **หลักร้อย MB ถึง 2-3 GB**

→ **ดิสก์ 80 GB สบายมาก** แต่ควรตั้ง alert ที่ 70% ไว้

### สิ่งที่ต้องกังวลจริงๆ คือ backup ไม่ใช่ความจุ

ทุกอย่างอยู่บนเครื่องเดียว เครื่องพัง = ข้อมูลผู้เข้างาน 5,000 คนหายหมด
snapshot ของผู้ให้บริการ VPS ไม่นับ (ถ่ายวันละครั้ง และกู้ทีต้องกู้ทั้งเครื่อง)

มีสคริปต์ให้แล้ว — ทดสอบวงจร dump → ลบฐานข้อมูลทิ้ง → restore ครบแล้ว:

```bash
cd backend && ./scripts/backup.sh
```

ระหว่างงาน 3 วันตั้ง cron ทุกชั่วโมง:

```cron
0 * * * * cd /srv/egoke/backend && ./scripts/backup.sh >> /var/log/egoke-backup.log 2>&1
```

★ ไฟล์ backup อยู่บนเครื่องเดียวกับของจริงไม่นับเป็น backup — `scp` ออกไปเก็บที่อื่นด้วย
★ ไฟล์นี้มีข้อมูลส่วนบุคคลทั้งหมด ปฏิบัติกับมันเหมือนรหัสผ่าน

---

## 3. ขั้นตอน deploy

### 3.1 เตรียมโดเมน

ตั้ง A record สองตัวชี้มาที่ IP ของ VPS:

```
api.egoke2026.com   A   <IP ของ VPS>
app.egoke2026.com   A   <IP ของ VPS>
```

★ **สองโดเมนต้องอยู่ใต้โดเมนจดทะเบียนเดียวกัน**
refresh token เป็น cookie `SameSite=Lax` เบราว์เซอร์ส่งข้ามให้ก็ต่อเมื่อเป็น "site" เดียวกัน
ถ้าเอาหน้าเว็บไปไว้ `egoke.vercel.app` แล้ว API อยู่ `api.egoke2026.com`
= คนละ site = ไม่ส่ง cookie = **หลุด login ทุก 15 นาที โดยไม่มี error ให้เห็น**
(จะใช้ Vercel ก็ได้ แต่ต้องผูก custom domain เป็น `app.egoke2026.com` ก่อน)

### 3.2 ติดตั้งบน VPS

```bash
# ติดตั้ง docker
curl -fsSL https://get.docker.com | sh

# ★ firewall — เปิดแค่ 3 port เท่านั้น
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw enable

git clone <repo> /srv/egoke && cd /srv/egoke/backend
```

### 3.3 สร้าง secret

```bash
./scripts/deploy-init.sh
```

สร้าง `.env.production` พร้อมสุ่ม secret 8 ตัว และสร้าง mongo keyfile ให้
แล้วบอกว่าเหลืออะไรต้องกรอกเอง — กรอกให้ครบแล้วรันซ้ำได้ (ไม่ทับค่าที่กรอกไว้)

ค่าที่ต้องกรอกเอง: `API_DOMAIN` `APP_DOMAIN` `FRONTEND_ORIGIN` `API_BASE_URL`
`GOOGLE_REDIRECT_URI` `CERTBOT_EMAIL` `GOOGLE_CLIENT_ID` `GOOGLE_CLIENT_SECRET` `ADMIN_EMAILS`

### 3.4 ตั้งค่า Google Cloud Console

ถ้าข้ามข้อนี้ ล็อกอินไม่ได้ทั้งระบบ:

1. **Authorized redirect URIs** → `https://app.egoke2026.com/login` (ต้องตรงกับ `GOOGLE_REDIRECT_URI` เป๊ะทุกตัวอักษร)
2. **Authorized JavaScript origins** → `https://app.egoke2026.com`
3. **OAuth consent screen** → External แล้วกด **Publish app**
   ★ ถ้ายังเป็น Testing จะล็อกอินได้แค่อีเมลในลิสต์ (สูงสุด 100 คน) — งานนี้มี 5,000 คน

### 3.5 ขึ้นระบบ

```bash
C="docker compose -f docker-compose.prod.yml --env-file .env.production"

# ซ้อมขอใบรับรองก่อน (Let's Encrypt จำกัดความล้มเหลว 5 ครั้ง/ชม./โดเมน)
$C up -d --build
./scripts/deploy-cert.sh --staging

# ผ่านแล้วค่อยเอาของจริง
./scripts/deploy-cert.sh

# ถ้าจะรันหน้าเว็บบนเครื่องนี้ด้วย
$C --profile web up -d --build web

$C ps
curl https://api.egoke2026.com/healthz
```

### 3.6 ตั้ง index กับข้อมูลตั้งต้น

```bash
$C exec api python -m scripts.init_indexes
$C exec api python -m scripts.import_artists
```

---

## 4. รายการตรวจก่อนวันงาน

| ตรวจอะไร | คำสั่ง | ที่ควรเห็น |
|---|---|---|
| ไม่มี port ฐานข้อมูลหลุด | `docker ps --format '{{.Names}}\t{{.Ports}}'` | มีแต่ nginx ที่มี `0.0.0.0:` |
| mongo ต้องใช้รหัสผ่าน | `$C exec mongo mongosh --eval 'db.users.find()'` | `requires authentication` |
| redis ต้องใช้รหัสผ่าน | `$C exec redis redis-cli ping` | `NOAUTH` |
| เอกสาร API ปิดแล้ว | `curl -s -o /dev/null -w '%{http_code}' https://api.../docs` | `404` |
| HTTPS ใช้ได้ | เปิด `https://app.egoke2026.com` บนมือถือ | กุญแจล็อก ไม่มีคำเตือน |
| **กล้องเปิดได้** | เปิด `/scan` บนมือถือจริง กด "เปิดกล้อง" | เห็นภาพจากกล้อง |
| SSE ไหลจริง | `curl -N 'https://api.../v1/me/stream?token=...'` | `retry: 5000` ทันที แล้ว `: ping` ทุก 25 วิ |
| backup ทำงาน | `./scripts/backup.sh` | ได้ไฟล์ 2 ไฟล์ |

★ ข้อ "กล้องเปิดได้" ต้องทดสอบบนมือถือจริงผ่าน HTTPS จริง — `getUserMedia`
ใช้ได้เฉพาะ secure context ทดสอบบน localhost จะผ่านเสมอ แล้วไปพังหน้างาน

---

## 5. กับดักที่เคยเสียเวลาไปแล้ว

### `docker compose restart` ไม่อ่าน `.env` ใหม่

environment ถูกฝังตอน **สร้าง** container ไม่ใช่ตอนสตาร์ท
เคยแก้ `ALLOWED_EMAIL_DOMAINS` แล้ว restart แล้วงงว่าทำไมไม่เปลี่ยน

```bash
$C up -d --force-recreate api ws worker broadcaster
```

ตอนนี้ api log ค่าที่ใช้จริงตอน startup แล้ว (`auth_policy_effective`, `grant_limits_effective`)
สงสัยเมื่อไหร่ให้ดูที่นั่น อย่าเดาจากไฟล์

### `NEXT_PUBLIC_API_BASE` ฝังตอน build

ตั้งใน environment ของ container ไม่มีผล เปลี่ยนโดเมนต้อง build image ใหม่

### nginx `add_header` ไม่สืบทอดแบบที่คิด

location ที่มี `add_header` ของตัวเองจะ**ทิ้ง** `add_header` ทั้งหมดจาก server block
ไม่ใช่รวมกัน — HSTS หายเงียบๆ โดย `nginx -t` ผ่าน
ทุก location ที่มี `add_header` เอง ต้อง `include security_headers.conf` ซ้ำ
(`tests/test_deploy_config.py` เฝ้าข้อนี้ให้แล้ว)

### ไม่มี rate limit ต่อ IP ใน nginx — ตั้งใจ

ผู้เข้างาน 5,000 คนต่อ wifi มหาวิทยาลัยเส้นเดียวกัน = ออกเน็ตด้วย public IP ไม่กี่ตัว (NAT)
ในสายตา nginx คือ "คนเดียว" — `rate=100r/m` จะทำให้ทั้งงานใช้เว็บไม่ได้ตั้งแต่ 9 โมง
การกันยิงรัวของจริงอยู่ที่ `app/core/ratelimit.py` ซึ่งนับต่อผู้ใช้ ไม่ใช่ต่อ IP

### ถ้าใช้ Cloudflare

ต้องเปิดบล็อก `set_real_ip_from` (เปิดไว้แล้วใน template) ไม่งั้น IP ทุกคนจะกลายเป็น
IP ของ Cloudflare — log ไร้ประโยชน์ และ rate limit ใดๆ ที่คิดตาม IP จะเหมารวมทั้งงาน
และตอนขอใบรับรองครั้งแรกให้ปิด proxy (เมฆส้ม → เทา) ชั่วคราว
