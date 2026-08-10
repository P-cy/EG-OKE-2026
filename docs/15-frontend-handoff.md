# 15 — Frontend Handoff (ส่งต่อทีม Frontend)

> เอกสารนี้คือ "ทุกอย่างที่ frontend ต้องรู้" เพื่อรัน/แก้/ต่อโค้ดฝั่งเว็บ
> คู่กับ [16-features.md](16-features.md) (รายละเอียดแต่ละฟีเจอร์) และ [17-api-endpoints.md](17-api-endpoints.md) (API ทั้งหมด)

## Tech stack

| ตัว | เวอร์ชัน | หมายเหตุ |
|---|---|---|
| Next.js | `^16.3.0` | App Router, `output: "standalone"` (Docker) |
| React | `19.0.0` | |
| TypeScript | `^5.7.3` | strict |
| Tailwind CSS | `^3.4.17` | synthwave palette (ดู `tailwind.config.ts`) |
| TanStack Query | `^5.59.0` | server state + polling |
| Zustand | `^5.0.3` | auth store + notify store |
| qrcode.react | `^4.2.0` | `QRCodeSVG` สำหรับหน้าบัตร |
| @zxing/browser | `^0.1.5` | กล้องสแกน QR หน้า `/scan` |
| Vitest | `^3.2.7` | unit test |

ไม่มี `framer-motion`, `next-auth`, SWR — chart ทำเองด้วย div, OAuth เขียนเอง, data fetching ใช้ TanStack Query ตัวเดียว

## โครงสร้างโฟลเดอร์

```
frontend/
├── src/
│   ├── app/                    # App Router (ทุกหน้า)
│   │   ├── layout.tsx          # root layout: <Providers><Layout>{children}
│   │   ├── page.tsx            # / หน้าหลัก
│   │   ├── login/              # /login
│   │   ├── onboarding/         # /onboarding
│   │   ├── ticket/             # /ticket  (QR บัตร)
│   │   ├── vote/               # /vote
│   │   ├── ig/                 # /ig  (ส่งโพสต์ขึ้นจอ)
│   │   ├── wheel/              # /wheel  (ตู้สล็อต)
│   │   ├── points/             # /points  (ประวัติ coin)
│   │   ├── profile/            # /profile
│   │   ├── quests/             # /quests  (กิจกรรมบูธ)
│   │   ├── scan/               # /scan  (staff/admin สแกน)
│   │   ├── admin/              # /admin/*  (มี layout.tsx ของตัวเอง)
│   │   ├── staff/              # /staff/*  (มี layout.tsx ของตัวเอง)
│   │   └── display/            # /display/*  (จอใหญ่ ไม่มี nav)
│   ├── components/             # component กลาง
│   ├── lib/                    # api, auth, notify, providers, format, faculty
│   └── globals.css             # theme + keyframes
├── next.config.mjs             # output: standalone, remotePatterns
├── tailwind.config.ts          # palette neon + fonts
├── .env.local                  # NEXT_PUBLIC_API_BASE
└── package.json
```

## ทุกหน้า (รวม route map)

### หน้าผู้ใช้ (login แล้ว)

| Route | ไฟล์ | ทำอะไร |
|---|---|---|
| `/` | `app/page.tsx` | หน้าหลัก: โลโก้ + ประกาศ + stat tiles (poll snapshot 3s) + การ์ดลิงก์ (vote/ig/wheel/ticket) + ยอด coin |
| `/login` | `app/login/page.tsx` | Google OAuth ปุ่มเดียว + รับ callback `?code=&state=` |
| `/onboarding` | `app/onboarding/page.tsx` | กรอก ชื่อเล่น/คณะ/ภาค/รหัสนักศึกษา/ยอมรับ consent → บันทึกแล้วออกบัตร QR อัตโนมัติ |
| `/ticket` | `app/ticket/page.tsx` | บัตร QR 1 ใบใช้ทั้ง 3 วัน + rotating code + badge วัน 1/2/3 + WakeLock + cache offline |
| `/vote` | `app/vote/page.tsx` | โหวตศิลปิน (poll รอบ 5s, ผล 3s) + modal ยืนยันก่อนส่ง |
| `/ig` | `app/ig/page.tsx` | ส่งรูปขึ้นจอใหญ่ (จ่าย coin) — downscale 1440px JPEG q0.82 ฝั่ง client ก่อนอัป |
| `/wheel` | `app/wheel/page.tsx` | ตู้สล็อต 3 รีล + คันโยก + provably-fair (commit_hash) |
| `/points` | `app/points/page.tsx` | ยอด coin + ledger เต็ม (cursor pagination) |
| `/profile` | `app/profile/page.tsx` | wrapper `<ProfileCard/>` |
| `/quests` | `app/quests/page.tsx` | กิจกรรมบูธ: รายการ quest + ความคืบหน้า + ปุ่มเปิด /ticket ให้ staff สแกน |

### หน้า Admin (gated `roles={["admin"]}`, มี layout ชมพู)

| Route | ทำอะไร |
|---|---|
| `/admin` | แดชบอร์ด: tiles ผู้ใช้/เช็คอิน/โหวต/IG/wheel + checklist (poll 5s) |
| `/admin/attendees` | เช็คชื่อมือ (ค้นหา/กรอง) — admin กด undo ได้ |
| `/admin/quests` | CRUD quest (สร้าง/แก้/เปิด-ปิด/ลบ — ลบอันที่มี claim แล้วจะกลายเป็นปิดแทน) |
| `/admin/rounds` | ควบคุมรอบโหวต: เปิด/ปิด (freeze ผล)/ประกาศผล |
| `/admin/ig` | คิว IG: ภาพ/แคปชัน/flag → อนุมัติ/ปฏิเสธ + ปุ่ม clear wall |
| `/admin/users` | จัดการผู้ใช้: ค้นหา + ตั้ง role + ปรับ coin (ต้องใส่เหตุผล) |
| `/admin/grants` | เฝ้าระวัง staff grant: pair ranking (สัญญาณทุจริต) + reset budget |
| `/admin/export` | ดาวน์โหลด CSV: checkin/attendees/coins (เวลาไทย Excel-ready) |
| `/admin/audit` | audit log: infinite scroll + กรอง action + before/after diff |
| `/admin/config` | ฉุกเฉิน: maintenance/read-only/toggle ฟีเจอร์/ประกาศ |

### หน้า Staff (gated `roles={["staff","admin"]}`, มี layout เขียว)

| Route | ทำอะไร |
|---|---|
| `/staff` | หน้าหลัก staff: tiles ใหญ่ (สแกนเช็คอิน/สแกนจ่าย coin/ค้นชื่อ) + `<CheckinStatsCard/>` |
| `/staff/attendees` | เช็คชื่อมือ (reuse `<AttendeeCheckin mode="staff"/>` — **ไม่มี undo**) |
| `/scan` | สแกนเนอร์ PWA — 2 โหมด: `checkin` (ประตู) / `coins` (บูธจ่าย coin) |

### จอ Display (ไม่มี nav/header)

| Route | ทำอะไร |
|---|---|
| `/display/ig` | IG wall: ทีละโพสต์ 45s + ช่องว่าง 3s (ต้องมี `?token=DISPLAY_TOKEN`) |
| `/display/vote` | กราฟโหวตสด (poll 1s) |

## Navigation

### userNav (`components/Layout.tsx`)
```ts
const userNav = [
  { href: "/", label: "หน้าหลัก" },
  { href: "/quests", label: "กิจกรรม" },
  { href: "/vote", label: "โหวต" },
  { href: "/ig", label: "ส่ง IG" },
  { href: "/points", label: "coin" },
  { href: "/wheel", label: "วงล้อ" },
  { href: "/ticket", label: "บัตร" },
  { href: "/profile", label: "โปรไฟล์" },
];
```
Header แสดงปุ่มเขียว "Staff" (ถ้าเป็น staff ไม่ใช่ admin) หรือชมพู "Admin" (ถ้าเป็น admin) + "ออก"

### adminNav (`app/admin/layout.tsx`)
```ts
const adminNav = [
  { href: "/admin", label: "แดชบอร์ด" },
  { href: "/scan", label: "สแกน QR", external: true },
  { href: "/admin/attendees", label: "เช็คชื่อด้วยมือ" },
  { href: "/admin/quests", label: "กิจกรรม" },
  { href: "/admin/rounds", label: "รอบโหวต" },
  { href: "/admin/ig", label: "คิว IG" },
  { href: "/admin/users", label: "ผู้ใช้" },
  { href: "/admin/grants", label: "เหรียญที่จ่าย" },
  { href: "/admin/export", label: "ดาวน์โหลด" },
  { href: "/admin/audit", label: "ประวัติ" },
  { href: "/admin/config", label: "ฉุกเฉิน" },
];
```

### staffNav (`app/staff/layout.tsx`)
```ts
const staffNav = [
  { href: "/staff", label: "หน้าหลัก" },
  { href: "/scan", label: "สแกน QR", external: true },
  { href: "/staff/attendees", label: "ค้นรายชื่อ" },
];
```

## Components (`src/components/`)

| Component | หน้าที่ |
|---|---|
| `Layout.tsx` | shell หน้าผู้ใช้ (ธีมน้ำเงิน) — login/onboarding redirect, refreshUser ตอน focus/pathname |
| `ProtectedRoute.tsx` | guard — redirect `/login` ถ้าไม่มี token, redirect `/` ถ้า role ไม่ผ่าน; `superadmin` ผ่านหมด |
| `NeonButton.tsx` | ปุ่มธีม: pink/blue/purple/ghost/danger + `loading` |
| `RetroCard.tsx` | การ์ด `glow`: pink/blue/purple/green/none + `title` |
| `Spinner.tsx` | วงแหวนหมุน ปรับ `size` ได้ |
| `Toaster.tsx` | toast bus — `toast(msg, level)` auto-dismiss 3.5s |
| `ProfileCard.tsx` | ดู/แก้โปรไฟล์ + อัป avatar (cover-crop 256×256) + **ดาวน์โหลดข้อมูลของฉัน (PDPA)** |
| `AttendeeCheckin.tsx` | เช็คชื่อมือ share ระหว่าง admin/staff (`mode="admin"|"staff"`) — admin กด badge เขียวเพื่อ undo ได้ |
| `CheckinStatsCard.tsx` | stat เช็คอินสด (poll 5s) |
| `CheckinModal.tsx` | modal คงอยู่ที่เด้งตอนถูกสแกน → ชวนกรอกฟอร์ม Attendance (ซ่อนใน /scan /admin /display) |
| `IGSubmissionRow.tsx` | แถวใน list "ส่ง IG ของฉัน" |

## Lib (`src/lib/`)

| ไฟล์ | หน้าที่ |
|---|---|
| `api.ts` | API client — `apiFetch`, `ApiError`, `setToken`, `downloadFile`, `newIdemKey`, ~45 endpoint methods + types |
| `auth.ts` | Zustand auth store (persist localStorage `egoke-auth`) — token เป็น source of truth |
| `notify.ts` | Zustand `useNotifyStore` + `useCheckinNotify()` (SSE hook) |
| `providers.tsx` | React Query + `<Toaster/>` + `<CheckinModal/>` + `<NotifyManager/>` (เปิด SSE + re-show AT prompt) |
| `format.ts` | Thai format helpers — `formatCoins`, `parseServerTime` (guard 7h drift), `formatTime`, `countdown`, `igLabel` |
| `faculty.ts` | taxonomy คณะ/ภาคมหิดล + `facultyDisplay()` |

### สิ่งสำคัญใน `api.ts`
- `BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/v1"`
- ทุก POST/PUT/PATCH/DELETE ใส่ `Idempotency-Key` อัตโนมัติ (ผ่าน `newIdemKey` — มี fallback สำหรับ http LAN ที่ไม่มี `crypto.randomUUID`)
- 401 → refresh ครั้งเดียว (de-dup) แล้ว silent redirect `/login`
- `downloadFile` — ดาวน์โหลด blob พร้อม Authorization header (`<a>` ทำเองไม่ได้)
- SSE **ไม่** ผ่าน `apiFetch` — `lib/notify.ts` เปิด `EventSource` เอง (ส่ง token ใน query เพราะ EventSource ใส่ header ไม่ได้)

## Theme (สำคัญ — อย่าแก้นอกจากจำเป็น)

ดู `tailwind.config.ts` + `globals.css`:
- **สี neon**: `neon-pink #ff2d95`, `neon-purple #b026ff`, `neon-blue #00e5ff`, `neon-yellow #ffe600`, `neon-green #39ff14`, `neon-red #ff3b3b`
- **พื้น**: `bg-deep #0a0118`, `bg-panel #140a2e`, `bg-panel2 #1d1042`
- **ฟอนต์**: `display` "Press Start 2P", `mono` "VT323", `body` "Noto Sans Thai"
- helper class: `neon-text-pink/blue/purple`, `neon-border-pink/blue/purple`, `retro-panel`, `scanlines`, `animate-flicker`
- พื้นหลัง perspective grid + sun glow อยู่ใน `body::before`/`body::after`

## วิธีรัน (Development)

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
```

ต้องรัน backend คู่กัน (ดู [11-local-testing-guide.md](11-local-testing-guide.md)):
```bash
cd backend
docker compose up -d          # mongo + redis + api + ws + worker + broadcaster
```

## วิธี build + รัน production (Docker)

```bash
# ★ NEXT_PUBLIC_API_BASE ฝังตอน build ไม่ใช่ runtime — ต้องใส่ตอน docker build
docker build \
  --build-arg NEXT_PUBLIC_API_BASE=https://api.โดเมนคุณ/v1 \
  -t egoke-web \
  frontend/

docker run -p 3000:3000 egoke-web     # รันเป็น non-root (uid 1001)
```

หรือ build แบบไม่ใช้ Docker:
```bash
NEXT_PUBLIC_API_BASE=https://api.โดเมนคุณ/v1 npm run build
npm run start
```

## Env var

มีแค่ตัวเดียว:

| Var | ค่า default | หมายเหตุ |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8000/v1` | **ฝังตอน `next build`** runtime env ไม่มีผล |

⚠️ **ข้อควรระวัง (จาก `.env.example`):** โดเมน API ต้อง share parent domain เดียวกับเว็บ เพราะ refresh token ใช้ cookie `SameSite=Lax` — ถ้า API กับ web คนละ parent domain (เช่น Vercel subdomain + custom API domain) refresh จะไม่ทำงาน คนจะถูกล็อกเอาท์ทุก 15 นาที

## Test

```bash
npm run test           # vitest run
npm run test:watch
npm run typecheck      # tsc --noEmit
npm run lint           # next lint
```

## กฎเหล็ก (สืบทอดจาก [00-OVERVIEW.md](00-OVERVIEW.md))

1. ทุก state-changing request ต้องมี `Idempotency-Key` (api.ts ใส่ให้อัตโนมัติ — อย่าลบ)
2. coin balance ไม่ใช่ source of truth — `coin_transactions` ledger คือ; balance ใน auth store เป็น cache
3. ผลวงล้อตัดสินที่ server (HMAC) — frontend แค่ animate
4. อย่าเก็บข้อมูล sensitive ใน localStorage นอกจาก `access_token` (15 นาที) + `user` profile (ไม่มี secret)
5. ทุกหน้าต้องทนตอน offline/เน็ตแย่ (งานอีเวนต์ WiFi ไม่ดี) — ใช้ TanStack Query retry + optimistic UI

## เริ่มต้นแก้โค้ด — อ่านอะไรก่อน

1. [16-features.md](16-features.md) — เข้าใจฟีเจอร์ที่จะแก้
2. [17-api-endpoints.md](17-api-endpoints.md) — endpoint ที่เกี่ยวข้อง
3. `src/lib/api.ts` — ดู type + method ที่มี
4. ไฟล์หน้านั้นๆ ใน `src/app/...`
5. `tailwind.config.ts` + `globals.css` — theme
