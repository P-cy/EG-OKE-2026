# EG'OKE 2026

## สารบัญ

- [เอกสารออกแบบระบบ](#เอกสารออกแบบระบบ)
- [โครงสร้างทีม](#โครงสร้างทีม)
  - [Frontend Team — ระบบหน้าบ้าน](#frontend-team--ระบบหน้าบ้าน)
  - [Backend Team — ระบบหลังบ้าน](#backend-team--ระบบหลังบ้าน)
  - [Onsite Team — หน้างาน](#onsite-team--หน้างาน)

---

## เอกสารออกแบบระบบ

| เอกสาร | เนื้อหา |
|---|---|
| [docs/00-OVERVIEW.md](docs/00-OVERVIEW.md) | สรุปพารามิเตอร์งาน + non-negotiables |
| [docs/01-architecture.md](docs/01-architecture.md) | สถาปัตยกรรม, กลยุทธ์กัน burst, degraded mode |
| [docs/02-database-schema.md](docs/02-database-schema.md) | MongoDB collections + index ทั้งหมด |
| [docs/03-api-spec.md](docs/03-api-spec.md) | REST endpoints + error model + rate limits |
| [docs/04-realtime.md](docs/04-realtime.md) | WebSocket, polling, วงล้อ provably-fair |
| [docs/05-infrastructure.md](docs/05-infrastructure.md) | Contabo sizing, Docker, backup, failover runbook |
| [docs/06-security.md](docs/06-security.md) | Threat model, anti-cheat, QR, PDPA |
| [docs/07-cost.md](docs/07-cost.md) | ค่าใช้จ่าย ~฿4,300 ตลอดโปรเจกต์ |
| [docs/08-workplan.md](docs/08-workplan.md) | แผนงาน 8 สัปดาห์ + load test + runbook |
| [docs/09-frontend-plan.md](docs/09-frontend-plan.md) | โครง frontend + จุดที่ต้องทำถูก |
| [backend/](backend/) | โค้ด FastAPI ที่รันได้จริง (`docker compose up`) |

**สเปกที่ออกแบบไว้:** 5,000 คน · 3 วัน · peak 1,500 rps · MongoDB + Redis + FastAPI · Contabo 3 เครื่อง · ~฿1,064/เดือน

---

## โครงสร้างทีม

### Frontend Team — ระบบหน้าบ้าน

- ออกแบบและพัฒนาเว็บไซต์ให้รองรับ **โทรศัพท์ แท็บเล็ต และคอมพิวเตอร์** (Responsive Design) รวมถึงหน้า **Login, Home และ Profile**
- พัฒนาหน้าฟังก์ชันต่าง ๆ เช่น โหวตศิลปิน ส่ง Instagram ดูคะแนนสะสม รวมถึงหน้าวงล้อ จอแสดงกิจกรรม และตรวจสอบสถานะคำขอ
- ดูแลภาพรวมของหน้าบ้านให้ **ใช้งานง่าย สวยงาม และสอดคล้องกับธีม** ของงาน

---

### Backend Team — ระบบหลังบ้าน

- พัฒนาเว็บสำหรับการเข้าสู่ระบบผ่าน **อีเมลมหาวิทยาลัย** เพื่อยืนยันตัวตนของผู้เข้าร่วมงาน
- ออกแบบฐานข้อมูลสำหรับข้อมูลผู้ใช้ บัตรเข้างาน คะแนน การโหวต และคำขอศิลปิน
- พัฒนา **API** เชื่อมต่อระหว่างเว็บไซต์ ระบบฐานข้อมูล และหน้าควบคุมของเจ้าหน้าที่
- ดูแลระบบ **QR Code** สำหรับตรวจสอบสิทธิ์เข้างาน
- จัดเตรียมระบบ **Admin** ระบบสำรองข้อมูล และ **Backup Server** สำหรับกรณีระบบหลักมีปัญหา

---

### Onsite Team — หน้างาน

- ติดตั้งและตรวจสอบคอมพิวเตอร์ จอแสดงผล ระบบอินเทอร์เน็ต และอุปกรณ์ IT ก่อนเริ่มงาน
- ดูแลจุดลงทะเบียนและตรวจสอบ **QR Code** ของผู้เข้าร่วมงานบริเวณทางเข้า
- ควบคุมข้อมูลที่แสดงบนจอ เช่น ผลโหวต คะแนน Instagram และวงล้อสุ่มรางวัล
- ให้ความช่วยเหลือและแก้ไขปัญหาด้านเว็บไซต์ ระบบเครือข่าย และอุปกรณ์ IT ภายในงาน
- แก้ไขปัญหาฉุกเฉินหน้างาน เช่น อินเทอร์เน็ต คอมพิวเตอร์สำรอง และระบบ Backup อื่น ๆ

---