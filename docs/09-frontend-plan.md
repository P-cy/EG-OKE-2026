# 09 — Frontend Plan (คร่าวๆ)

> เอกสารนี้ตั้งใจให้คร่าวๆ ตามที่ตกลง — เน้น backend ก่อน แต่ระบุ **จุดที่ frontend ต้องทำถูก ไม่งั้น backend ที่ดีก็ช่วยไม่ได้**

## 1. Stack

| ส่วน | เลือก | เหตุผล |
|---|---|---|
| Framework | **Next.js 15 (App Router)** หรือ Vite + React | Next ได้ SSR หน้า public + image optimization |
| Hosting | **Cloudflare Pages** (ฟรี) | แยกจาก app-1 → ลด load 40% + เร็วกว่า |
| Styling | Tailwind CSS | เร็ว, responsive ง่าย, ทีมเรียนรู้ไว |
| Data fetching | TanStack Query | cache + retry + polling ในตัว |
| State | Zustand | เบา ไม่ต้อง boilerplate |
| Animation | Framer Motion | วงล้อ + transition |
| QR gen | `qrcode.react` | render ฝั่ง client |
| QR scan | `@zxing/browser` หรือ `html5-qrcode` | อ่านจากกล้อง |
| Chart | Recharts | leaderboard, ผลโหวต |

## 2. Route map

### ผู้เข้าร่วม (mobile-first)
```
/                    หน้า Home — ประกาศ, ตารางงาน, ทางลัด
/login               ปุ่ม "เข้าสู่ระบบด้วยอีเมลมหิดล"
/onboarding          กรอกชื่อเล่น, IG handle, ยินยอม PDPA
/profile             โปรไฟล์ + คะแนน + อันดับ
/ticket              ★ QR + rotating code (หน้าที่คนเปิดบ่อยที่สุด)
/vote                โหวตศิลปิน
/vote/results        ผลโหวต (ถ้าเปิดให้ดู)
/ig                  ส่งลิงก์ IG + ดูสถานะคำขอ
/points              ประวัติคะแนน (ledger ของตัวเอง)
/leaderboard         อันดับคะแนน + อันดับ IG
/wheel               วงล้อ
```

### จอแสดงผลหน้างาน (16:9, ไม่มี interaction)
```
/display/vote        ผลโหวตสด (bar chart ใหญ่)
/display/ig?token=   IG wall — ★ ต้องมี ?token=DISPLAY_TOKEN
```

★ มีแค่สองหน้านี้ ที่เหลือเคยวางแผนไว้แต่ไม่ได้ทำ:
`/display/wheel` `/display/leaderboard` `/display/checkin` — ไม่มีในโค้ด

★ `/display/rotate` (สลับหน้าอัตโนมัติ) **ถูกลบทิ้งแล้ว** — มันสลับทุก 30 วิ
ขณะที่ IG wall ฉายใบละ 45 วิ พอสลับกลับมาหน้าถูก mount ใหม่ คิวรีเซ็ต
= ขึ้นใบแรกซ้ำไม่จบ (และตัวมันเองก็สลับได้ครั้งเดียวแล้วหยุด เพราะ
`router.push` ทำให้หน้า rotate ถูก unmount ไปพร้อม interval)
ถ้าอยากได้หลายจอ ให้เปิดคนละหน้าคนละจอไปเลย

### Staff / Admin
```
/scan                ★ Scanner PWA (offline-first)
/admin               dashboard
/admin/users         จัดการผู้ใช้
/admin/ig            คิว moderation
/admin/vote-rounds   คุมรอบโหวต
/admin/wheel         คุมวงล้อ
/admin/config        ⚡ ปุ่มฉุกเฉิน
```

## 3. Responsive breakpoints

| ขนาด | Tailwind | รองรับอะไร |
|---|---|---|
| < 640px | default | **มือถือ = 90% ของ traffic** ออกแบบตรงนี้ก่อน |
| 640–1024px | `sm:` `md:` | แท็บเล็ต (scanner ใช้ขนาดนี้) |
| > 1024px | `lg:` | คอมพิวเตอร์ (admin ใช้ขนาดนี้) |
| > 1920px | `2xl:` | **จอแสดงผลหน้างาน — ฟอนต์ต้องใหญ่มาก** อ่านจากระยะ 20 เมตร |

> จอหน้างานคือ breakpoint ที่คนลืมบ่อยที่สุด — ตัวหนังสือขนาด `text-9xl` ขึ้นไป, contrast สูง, ไม่มี hover state

## 4. จุดที่ Frontend ต้องทำถูก (สำคัญกว่าความสวย)

### 4.1 Polling ที่ไม่ฆ่า server
```js
// ✅ ต้องมี 3 อย่างนี้เสมอ
- exponential backoff เมื่อ error (1s → 2s → 4s → max 30s)
- jitter สุ่ม ±500ms  (ไม่งั้น 2,000 client ยิงพร้อมกันเป๊ะทุก 3 วิ)
- หยุด poll เมื่อ document.hidden === true
```
TanStack Query ตั้งได้:
```js
useQuery({
  queryKey: ['snapshot'],
  queryFn: fetchSnapshot,
  refetchInterval: (q) => document.hidden ? false : 3000 + Math.random() * 500,
  refetchIntervalInBackground: false,
  retry: 3,
  retryDelay: (n) => Math.min(1000 * 2 ** n, 30000),
});
```

### 4.2 Idempotency key ทุก POST
```js
const key = crypto.randomUUID();          // ★ สร้าง 1 ครั้ง ใช้ซ้ำตอน retry
async function vote(artistId) {
  return api.post('/votes', { artist_id }, { headers: { 'Idempotency-Key': key } });
}
```
ถ้าสร้าง key ใหม่ทุก retry = ไม่มีประโยชน์เลย

### 4.3 Optimistic UI + rollback
โหวตแล้วต้องเห็นผลทันที (backend คืน 202 อยู่แล้ว) แต่ถ้า error ต้องย้อนกลับและบอกผู้ใช้ให้ชัดเจนเป็นภาษาไทย

### 4.4 Scanner PWA — offline first (สำคัญที่สุดในฝั่ง FE)
```
Service Worker + IndexedDB
├─ สแกน → ตรวจ HMAC ในเครื่อง (ไม่ต้องรอเน็ต) → แสดงผลทันที < 100ms
├─ เก็บ queue ใน IndexedDB
├─ background sync → POST /checkin/batch เมื่อออนไลน์
├─ แสดง badge "ค้าง sync: 12 รายการ" ตลอดเวลา
└─ ★ ห้ามล้าง queue จนกว่า server จะ ack
```
UX ที่ staff ต้องการ:
- **เสียง 3 แบบ** (ผ่าน / ซ้ำ / ไม่ผ่าน) — หน้างานเสียงดัง staff ไม่มองจอ
- **สั่น** ต่างจังหวะกัน
- **สีเต็มหน้าจอ** เขียว/เหลือง/แดง เห็นจากมุมตา
- แสดง **รูป + ชื่อ** ตัวใหญ่ ให้ staff เทียบหน้าคน
- ปุ่ม "ปล่อยผ่าน (override)" สำหรับ staff ระดับหัวหน้า + บันทึกเหตุผล

### 4.5 วงล้อ — animation ต้อง sync กับ server
```js
socket.on('wheel.arm', ({ starts_in_ms, server_time }) => {
  const offset = Date.now() - new Date(server_time);       // ชดเชย clock skew
  setTimeout(() => setCountdown(3), starts_in_ms - offset - 3000);
});

socket.on('wheel.spin', ({ segment_index, duration_ms }) => {
  const seg = 360 / segments.length;
  const deg = 360 * 8 + (360 - segment_index * seg) - seg / 2;
  wheelRef.current.style.transition = `transform ${duration_ms}ms cubic-bezier(.17,.67,.24,1)`;
  wheelRef.current.style.transform  = `rotate(${deg}deg)`;
});
```
**ห้าม `Math.random()` ที่ frontend เด็ดขาด** — ผลมาจาก server เท่านั้น

### 4.6 หน้า `/ticket` ต้องทำงานตอนเน็ตแย่
- cache QR payload ใน localStorage
- rotating code คำนวณจาก secret ที่ cache ไว้ + เวลาเครื่อง → ทำงาน offline ได้
- เพิ่มความสว่างหน้าจอเป็น 100% อัตโนมัติ (`navigator.wakeLock` + CSS) — QR สแกนติดง่ายขึ้นมาก
- ป้องกันหน้าจอดับด้วย Wake Lock API

## 5. Performance budget

| Metric | เป้าหมาย | เหตุผล |
|---|---|---|
| LCP (มือถือ 4G) | < 2.5s | คนต่อคิวหน้าประตู |
| Bundle แรก | < 200 KB gzip | WiFi งานช้าแน่นอน |
| `/ticket` โหลด | < 1s | เปิดบ่อยที่สุด |
| Lighthouse Performance | > 85 | |
| ทำงานตอน offline | หน้า `/ticket` + `/scan` | |

**วิธีให้ถึงเป้า:**
- Route-based code splitting (`next/dynamic`)
- รูปเป็น WebP/AVIF + `next/image`
- Font subset ภาษาไทย (`Noto Sans Thai` subset เฉพาะตัวที่ใช้ — ลดจาก 400KB เหลือ ~40KB)
- Preconnect ไป `api.egoke2026.example`
- Service Worker cache static assets

## 6. สิ่งที่ทีม FE ต้องคุยกับ BE ให้จบก่อน W2

- [ ] Freeze OpenAPI contract → generate TypeScript types อัตโนมัติ (`openapi-typescript`)
- [ ] ตกลง error code ทั้งหมด + ข้อความภาษาไทยที่จะแสดงให้ผู้ใช้เห็น
- [ ] ตกลง WS event schema
- [ ] ตกลงว่า mock server จะใช้อะไร (MSW) เพื่อ FE ไม่ต้องรอ BE
- [ ] ตกลง flow refresh token (FE ต้องรู้ว่าเจอ 401 แล้วทำอะไร)
