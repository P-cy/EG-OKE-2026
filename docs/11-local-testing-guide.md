# 11 — คู่มือทดสอบบนเครื่อง (Local Testing)

> ทดสอบทั้งหน้าคนปกติและหน้า Admin บนเครื่องของคุณ ก่อน deploy production
> ใช้เวลา setup ประมาณ 20-30 นาที (รวมสร้าง Google OAuth credential)

## สิ่งที่ต้องมีก่อนเริ่ม

- Docker + Docker Compose (รัน backend)
- Node.js 18+ (รัน frontend)
- บัญชี Google ที่ใช้อีเมล @student.mahidol.ac.th หรือ @mahidol.ac.th

---

## ขั้นที่ 1: สร้าง Google OAuth credential (ทำครั้งเดียว, ~5 นาที)

เพราะเราเลือกใช้ Google OAuth จริง ต้องมี Client ID/Secret ก่อน

> ★ **สำคัญมากถ้าอีเมลมหิดลเข้า Google Cloud ไม่ได้**
> อีเมลมหาลัย (Google Workspace for Education) ส่วนใหญ่ถูก IT admin
> ปิด Google Cloud Platform ไว้ → เข้า console ไม่ได้
> **แต่ไม่เป็นปัญหา:** ใช้ **Gmail ส่วนตัว** สร้าง project + credential แทน
> คน login ยังใช้เมลมหิดลได้ปกติ เพราะเจ้าของ project ไม่ใช่คนเดียวกับคน login
> การเช็ค "ต้องเป็นเมลมหิดลเท่านั้น" อยู่ที่ backend เรา ไม่ใช่ที่ Google

1. เปิด https://console.cloud.google.com/ ด้วย **Gmail ส่วนตัว**
   - ถ้าเจอหน้าเลือกองค์กร → เลือก **No organization** (ห้ามเลือกองค์กรมหิดล)
2. สร้าง project ใหม่ → ตั้งชื่อ `EGOKE-2026`
3. เมนู **APIs & Services → OAuth consent screen**
   - User type: **External** (ห้ามเลือก Internal — อันนั้นต้องเป็น Workspace องค์กร)
   - กรอกชื่อแอป `EGOKE 2026` + อีเมล support + developer contact (ใช้ Gmail คุณ)
   - Scopes: เพิ่ม `email`, `profile`, `openid`
   - Test users: เพิ่มอีเมลมหิดลของคุณเข้าไป (ระหว่าง testing ยังไม่ verified ต้องเพิ่ม)
4. เมนู **Credentials → Create Credentials → OAuth client ID**
   - Application type: **Web application**
   - Authorized JavaScript origins: `http://localhost:3000`
   - Authorized redirect URIs: `http://localhost:3000/login` (★ ต้องตรงกับ GOOGLE_REDIRECT_URI ใน .env)
5. กดสร้าง → จะได้ **Client ID** + **Client Secret** คัดลอกไว้
6. ไปเอาค่าใส่ใน `backend/.env` ที่ `GOOGLE_CLIENT_ID` และ `GOOGLE_CLIENT_SECRET`

> ตอนนี้แอปยังเป็นสถานะ "Testing" — คน login ได้มีแค่ที่อยู่ใน Test users
> พอขึ้น production จริง กด **PUBLISH APP** ใน consent screen แล้วขอ verified (2-6 สัปดาห์ ไม่บล็อกการทดสอบ)

> ฟรี 100% ไม่มีค่าใช้จ่าย ใช้ได้กับทุกอีเมลที่เพิ่มใน "Test users"

---

## ขั้นที่ 2: ใส่ค่าใน `.env`

ไฟล์ `backend/.env` สร้างให้แล้ว ค่าลับสุ่มให้หมด เหลือแค่ใส่ค่า Google:

```bash
# แก้ 2 บรรทัดนี้ใน backend/.env
GOOGLE_CLIENT_ID=ใส่ Client ID จากขั้นที่ 1
GOOGLE_CLIENT_SECRET=ใส่ Client Secret จากขั้นที่ 1
```

ค่าอื่นที่สำคัญ (ตั้งไว้ถูกต้องแล้ว อย่าแก้):
- `GOOGLE_REDIRECT_URI=http://localhost:3000/login` — ตรงกับที่ตั้งใน Google Console
- `ALLOWED_EMAIL_DOMAINS=student.mahidol.ac.th,mahidol.ac.th,mahidol.edu`
- `ADMIN_EMAILS=phatthanasak.kra@student.mahidol.ac.th` — ★ ใส่อีเมลที่จะใช้ login เป็น admin

> ถ้าอีเมลคุณไม่ใช่อันนี้ แก้ให้ตรงกับที่จะใช้ login จริง

---

## ขั้นที่ 3: รัน backend

```bash
cd backend

# รันครั้งแรก: สร้าง index + seed ข้อมูลทดสอบ
docker compose up -d

# รอให้ mongo+redis พร้อม (ประมาณ 10 วินาที) แล้ว seed
docker compose exec api python -m scripts.init_indexes
docker compose exec api python -m scripts.seed_dev
```

หลัง seed คุณจะมี:
- ศิลปิน 5 คน + รอบโหวต `d1-main` (เปิดอยู่)
- วงล้อ `main-wheel` (ราคา 20 คะแนน)
- ยังไม่มี user — ต้อง login เพื่อสร้าง

ตรวจว่ารันได้:
```bash
curl http://localhost:8000/healthz
# ต้องได้ {"status":"ok"}
```

---

## ขั้นที่ 4: รัน frontend

```bash
cd frontend
npm install          # ครั้งแรกเท่านั้น
npm run dev
```

เปิด http://localhost:3000

---

## ขั้นที่ 5: ทดสอบหน้าคนปกติ

1. เปิด http://localhost:3000 → กดปุ่มเข้าสู่ระบบ
2. Google จะถามเลือกบัญชี → เลือกอีเมลมหิดลของคุณ
3. ★ ถ้าอีเมลไม่ใช่โดเมนมหิดล → โดนปฏิเสธทันที (ทดสอบด้วย gmail.com ดู)
4. login สำเร็จ → redirect ไปหน้า onboarding (ครั้งแรก)
5. กรอกชื่อเล่น + เลือกคณะ EG + ภาค CO + ยินยอม → เข้าหน้าหลัก

ทดสอบแต่ละหน้า:
| หน้า | ทำอะไร |
|---|---|
| `/` | เห็นสถานะระบบสด การ์ดลัด |
| `/vote` | โหวตศิลปิน (มี 5 คนให้เลือก) |
| `/ig` | ★ ส่งรูป + IG handle (ต้องมีคะแนน — ถ้ายังไม่มี ให้ admin ปรับให้ก่อน) |
| `/wheel` | หมุนวงล้อ (ต้องมี 20 คะแนน) |
| `/ticket` | เห็น QR + rotating code |
| `/points` | ประวัติคะแนน |
| `/leaderboard` | อันดับคะแนน/IG |
| `/profile` | แก้โปรไฟล์ + คณะ/ภาค |

---

## ขั้นที่ 6: ทดสอบหน้า Admin

ถ้าคุณ login ด้วยอีเมลที่อยู่ใน `ADMIN_EMAILS`:

1. nav ด้านบนจะโชว์เมนู admin เพิ่มขึ้นมา (สีชมพู)
2. เข้าได้ที่:
   - `/admin` — แดชบอร์ด KPI
   - `/admin/ig` — ★ คิวตรวจ Instagram (อนุมัติ/ปฏิเสธ)
   - `/admin/users` — จัดการผู้ใช้ + ปรับคะแนน
   - `/admin/config` — ปุ่มฉุกเฉิน (ปิดฟีเจอร์/ประกาศ)

★ ทดสอบ flow IG wall ครบ:
1. login ด้วยบัญชีคนปกติ (อีเมลอื่น) → ไป `/ig` → ส่งรูป
2. logout → login ด้วยอีเมล admin → ไป `/admin/ig` → อนุมัติ
3. เปิด http://localhost:3000/display/ig → ต้องเห็นรูปขึ้นจอ

---

## ขั้นที่ 7: ทดสอบจอแสดงผล (Display)

เปิดในเบราว์เซอร์เต็มจอ (F11) — ออกแบบไว้สำหรับจอ 16:9:
- `/display/vote` — ผลโหวตสด
- `/display/ig?token=<DISPLAY_TOKEN>` — IG wall

★ มีแค่สองหน้านี้ (`/display/leaderboard` `/display/wheel` `/display/rotate`
เคยอยู่ในแผนแต่ไม่มีในโค้ด — rotate เคยมีแล้วถูกลบเพราะมันตัดจอ IG กลางคัน)

★ `?token=` ของหน้า IG ขาดไม่ได้ — ไม่มีแล้วจอจะแจ้ง "ฉายจบแล้ว" ไม่ได้
คิวไม่เดิน วนโพสต์เดิมไม่จบ (หน้าจอจะขึ้นกล่องเตือนสีเหลืองให้เห็น)
ค่าอยู่ใน `backend/.env` บรรทัด `DISPLAY_TOKEN=`

---

## ขั้นที่ 8: ทดสอบ Scanner (เจ้าหน้าที่)

1. login ด้วยบัญชี staff/admin → ไป `/scan`
2. ★ ตอนนี้ใส่ QR payload ด้วยมือ (ยังไม่เสียบกล้อง)
3. ดู payload จริงได้จากหน้า `/ticket` (copy มาแปะ)
4. ทดสอบ offline: ปิด WiFi → สแกน → เก็บในคิว → เปิด WiFi → sync อัตโนมัติ

---

## ปัญหาที่เจอบ่อย

| อาการ | วิธีแก้ |
|---|---|
| login แล้วโดนปฏิเสธ | อีเมลไม่ใช่โดเมนมหิดล หรือยังไม่ได้เพิ่มใน "Test users" ของ Google Console |
| login สำเร็จแต่ไม่มีเมนู admin | อีเมลไม่ได้อยู่ใน `ADMIN_EMAILS` ใน .env — แก้แล้ว logout+login ใหม่ |
| redirect_uri_mismatch | `GOOGLE_REDIRECT_URI` ใน .env ไม่ตรงกับที่ตั้งใน Google Console (ต้องเป็น `http://localhost:3000/login`) |
| หน้าขาว / error 500 | ดู log: `docker compose logs api -f` |
| frontend ต่อ backend ไม่ติด | เช็ค `frontend/.env.local` ว่า `NEXT_PUBLIC_API_BASE=http://localhost:8000/v1` |
| Mongo/Redis ไม่ขึ้น | `docker compose down -v` แล้ว `docker compose up -d` ใหม่ |

---

## ทดสอบแบบไม่ต้อง login (กำลังจะมี)

> ตอนนี้ยังไม่มี — ถ้าอยากทดสอบด่วนโดยไม่สร้าง Google credential ได้
> บอกผมเพิ่ม endpoint `/auth/dev-login` (เปิดเฉพาะ `ENV=development`)
> ที่สร้าง token จากอีเมลที่ใส่ ข้าม Google ไปเลย

---

## สรุปลำดับขั้นตอนสั้นๆ

```
1. สร้าง Google OAuth credential (Google Console)
2. ใส่ CLIENT_ID + SECRET ใน backend/.env
3. docker compose up -d (backend)
4. seed ข้อมูล (init_indexes + seed_dev)
5. npm run dev (frontend)
6. เปิด localhost:3000 → login → ทดสอบ
7. login ด้วยอีเมล admin → ทดสอบหน้า admin
```
