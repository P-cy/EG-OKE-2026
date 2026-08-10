# EG'OKE 2026 — System Design Overview

เอกสารชุดนี้แตกมาจาก `README.md` (ซึ่งเป็นแค่โครงสร้างทีม) ให้กลายเป็นสเปกระบบระดับ production

## สรุปพารามิเตอร์ของงาน

| หัวข้อ | ค่า |
|---|---|
| ผู้ใช้ลงทะเบียน | ~5,000 คน |
| ระยะเวลางาน | 3 วัน |
| ทราฟฟิกเฉลี่ย | 200–300 คน/ชั่วโมง (≈ 0.08 arrivals/s) |
| **Peak burst ที่ต้องรอด** | **~1,500 req/s เป็นเวลา 30–60 วินาที** |
| Auth | Google OAuth 2.0 + PKCE, จำกัด domain มหิดล |
| DB | MongoDB (replica set, self-hosted) |
| Cache/Realtime bus | Redis 7 |
| API | FastAPI (async) |
| Infra | Contabo VPS × 3 + Cloudflare Free |
| งบประมาณ | **≈ €28/เดือน (~1,060 บาท/เดือน)** |

## ทำไม peak ถึงเป็น 1,500 rps ทั้งที่เฉลี่ยแค่ 0.08/s

ค่าเฉลี่ยไม่มีความหมายเลยสำหรับงานอีเวนต์ ตัวที่ทำให้เว็บล่มคือ **moment ที่ทุกคนกดพร้อมกัน**:

| Moment | คนที่กดพร้อมกัน | หน้าต่างเวลา | rps ที่เกิด |
|---|---|---|---|
| MC ประกาศ "เปิดโหวตแล้ว" | ~2,000 | 30 วิ | ~600–1,500 |
| วงล้อกำลังจะหมุน | ~2,000 | ต่อเนื่อง | WS/poll 2,000 conn |
| ประกาศผล Leaderboard | ~2,000 | 20 วิ | ~800 |
| เปิดประตู (สแกน QR) | ~300 | 15 นาที | ~0.4 (ต่ำ แต่ต้อง p99 < 200ms) |

**หลักการออกแบบทั้งระบบคือ: ดูดซับ burst ไม่ใช่รองรับ throughput สูงตลอดเวลา**

## เอกสารในชุดนี้

### ออกแบบ/สถาปัตยกรรม (อ่านก่อน)
| ไฟล์ | เนื้อหา |
|---|---|
| [01-architecture.md](01-architecture.md) | สถาปัตยกรรม, การไหลของข้อมูล, กลยุทธ์กัน burst, HA |
| [02-database-schema.md](02-database-schema.md) | MongoDB collections ทุกตัว + index + เหตุผล |
| [03-api-spec.md](03-api-spec.md) | REST endpoints ทั้งหมด + error model + rate limit |
| [04-realtime.md](04-realtime.md) | WebSocket / SSE / snapshot broadcaster / วงล้อ provably-fair |
| [05-infrastructure.md](05-infrastructure.md) | VPS sizing, Docker Compose, Nginx, backup, failover runbook |
| [06-security.md](06-security.md) | Threat model, anti-cheat, QR anti-sharing, rate limiting |
| [07-cost.md](07-cost.md) | ค่าใช้จ่ายละเอียด + ตัวเลือกลดต้นทุน |
| [08-workplan.md](08-workplan.md) | แผนงานแยก module, timeline, definition of done |

### คู่มือใช้งาน/ส่งต่อ (อ่านตอนทำ)
| ไฟล์ | เนื้อหา |
|---|---|
| [09-frontend-plan.md](09-frontend-plan.md) | โครง frontend คร่าวๆ + route map + state strategy |
| [10-ig-wall-feature.md](10-ig-wall-feature.md) | รายละเอียดระบบ IG wall |
| [11-local-testing-guide.md](11-local-testing-guide.md) | ทดสอบบนเครื่อง + สร้าง Google OAuth credential |
| [12-checkin-system.md](12-checkin-system.md) | ระบบ QR check-in |
| [13-testing-and-load.md](13-testing-and-load.md) | load test |
| [14-deploy-vps.md](14-deploy-vps.md) | deploy production บน VPS |

### ★ Reference ล่าสุด (หลัง implement)
| ไฟล์ | เนื้อหา |
|---|---|
| [15-frontend-handoff.md](15-frontend-handoff.md) | **ส่งต่อ frontend** — ทุกหน้า/nav/component/lib + วิธีรัน/build/docker/env |
| [16-features.md](16-features.md) | **รายละเอียดแต่ละฟีเจอร์** — flow + config + ไฟล์ (auth, check-in, SSE/AT, quests, vote, IG, wheel, coins, export, audit, config) |
| [17-api-endpoints.md](17-api-endpoints.md) | **endpoint ทั้งหมด 58 ตัว** — แยกตามกลุ่ม + auth + body/response |

> เริ่มแก้โค้ดฝั่งเว็บ → อ่าน [15](15-frontend-handoff.md) ก่อน แล้วเข้า [16](16-features.md) (ฟีเจอร์) + [17](17-api-endpoints.md) (API)

โค้ดโครงร่างอยู่ที่ [`backend/`](../backend/) — รันได้จริงด้วย `docker compose up`

## Non-negotiables (ข้อที่ห้ามยอม)

1. **Vote/Check-in ห้ามเขียน MongoDB ตรงๆ ใน request path** → ผ่าน Redis + queue เสมอ
2. **คะแนนต้องเป็น append-only ledger** ไม่ใช่ integer ที่แก้ทับได้ (มีการโต้แย้งแน่นอน)
3. **ผลวงล้อต้องตัดสินที่ server** frontend มีหน้าที่แค่ animate
4. **ทุก write endpoint ต้อง idempotent** (มือถือในงานสัญญาณแย่ = กดซ้ำแน่นอน)
5. **ต้องมี read-only degraded mode** ถ้า Mongo ล่ม เว็บต้องยังแสดงผลและเช็คอินได้
