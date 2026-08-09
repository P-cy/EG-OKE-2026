# 06 — Security, Anti-Cheat & Privacy

## 1. Threat model — ใครจะโจมตีอะไร

| ผู้โจมตี | เป้าหมาย | ความน่าจะเป็น | ผลกระทบ |
|---|---|---|---|
| นักศึกษาที่อยากชนะ | ปั๊มคะแนน / โหวตซ้ำ | **สูงมาก** | สูง — เสียความน่าเชื่อถือทั้งงาน |
| คนไม่มีบัตร | ใช้ QR ของเพื่อน | **สูง** | กลาง — คนเกินความจุ = ปัญหาความปลอดภัย |
| นักศึกษาที่ชอบลอง | ยิง API เล่นๆ / SQL-NoSQL injection | สูง | กลาง |
| คนนอก | DDoS / defacement | ต่ำ | สูง |
| Insider (staff) | แก้คะแนนให้เพื่อน | **กลาง** | สูง |

**สังเกต:** ภัยอันดับ 1 ไม่ใช่แฮกเกอร์ต่างชาติ แต่คือ **นักศึกษาวิศวะที่ฉลาดและมีเวลาว่าง** — ออกแบบโดยคิดว่ามีคนอ่านโค้ด frontend ทุกบรรทัดแน่นอน

---

## 2. Authentication

### Google OAuth 2.0 + PKCE
```
1. GET /auth/google/login
   ├─ code_verifier = base64url(random(32))
   ├─ code_challenge = base64url(sha256(code_verifier))
   ├─ state = random(32)
   └─ Redis SETEX oauth:{state} 600 {verifier, redirect_uri}

2. Google → callback?code=...&state=...

3. POST /auth/google/callback
   ├─ ดึง state จาก Redis (ถ้าไม่มี = expired/CSRF → 400)  ★ ใช้ GETDEL, ใช้ได้ครั้งเดียว
   ├─ แลก code + code_verifier → id_token
   ├─ verify JWT signature ด้วย Google JWKS (cache 24h)
   ├─ ตรวจ aud == GOOGLE_CLIENT_ID, iss ∈ {accounts.google.com, https://accounts.google.com}, exp
   ├─ ตรวจ email_verified == true                          ★ ห้ามลืม
   ├─ ตรวจ domain ∈ ALLOWED_EMAIL_DOMAINS                   ★ กติกาหลักของงาน
   └─ upsert user by google_sub                             ★ ไม่ใช่ by email
```

> **ทำไม upsert ด้วย `google_sub` ไม่ใช่ `email`:** อีเมลเปลี่ยนได้/รีไซเคิลได้
> `sub` เป็น immutable identifier ของ Google — ถ้ามหาลัยรีไซเคิลอีเมลศิษย์เก่าให้รุ่นน้อง
> การ match ด้วย email จะทำให้รุ่นน้องได้บัญชีรุ่นพี่ไปเลย

### Token strategy
| Token | อายุ | เก็บที่ | หมายเหตุ |
|---|---|---|---|
| Access (JWT, HS256) | 15 นาที | memory ของ JS | ห้ามเก็บใน localStorage |
| Refresh (opaque, 32 bytes) | 30 วัน | httpOnly + Secure + SameSite=Lax cookie | rotate ทุกครั้งที่ใช้ |
| Display token | ตลอดงาน | env ของเครื่องจอ | อ่านอย่างเดียว, ผูก IP |
| Scanner token | 24 ชม. | secure storage ของ PWA | scope = checkin เท่านั้น |

**Access token payload**
```json
{ "sub": "<user_id>", "roles": ["participant"], "jti": "<ulid>",
  "iat": 1762089600, "exp": 1762090500, "ver": 1 }
```
- `jti` → ใส่ denylist ใน Redis ตอน logout (TTL = เวลาที่เหลือของ token)
- `ver` → เพิ่มเลขนี้ = kill token ทุกใบทั้งระบบทันที (ปุ่มฉุกเฉิน)
- **ห้ามใส่ `points_balance` หรือ `email` ใน JWT** — client ถอด base64 อ่านได้ และค่าจะ stale

### Refresh token rotation + reuse detection
```
ใช้ refresh token → ออกใบใหม่ + mark ใบเก่า replaced_by=ใบใหม่
ถ้ามีคนเอา "ใบเก่าที่ replaced แล้ว" มาใช้ → แปลว่าถูกขโมย
   → revoke ทั้ง family_id → บังคับ login ใหม่ทุกอุปกรณ์ + log security event
```

---

## 3. QR Code security

### รูปแบบ payload
```
EGOKE2:<qr_version>:<ticket_code>:<issued_ts>:<base64url(HMAC-SHA256[:16])>

HMAC = HMAC_SHA256(QR_SIGNING_KEY, "EGOKE2:<ver>:<code>:<ts>")
```
- **Scanner ตรวจ signature ได้เอง โดยไม่ต้องต่อเน็ต** ← นี่คือเหตุผลที่ใช้ HMAC ไม่ใช่ random UUID
- ตัด HMAC เหลือ 16 bytes → QR เล็กลง สแกนเร็วขึ้น ยังปลอดภัยพอ (128-bit)
- `qr_version` เพิ่ม 1 = **ยกเลิก QR ที่ออกไปแล้วทั้งหมด** (ถ้า key รั่ว)

### ปัญหา: คนแคปหน้าจอส่งให้เพื่อน

| ชั้นป้องกัน | วิธี | ประสิทธิภาพ |
|---|---|---|
| 1 | **One-time use** — `{user_id, event_day}` unique + `status: checked_in` | คนที่สแกนก่อนได้เข้า คนหลังโดนปฏิเสธ |
| 2 | **Rotating code (TOTP 6 หลัก, 30 วิ)** แสดงคู่กับ QR | ★ แคปหน้าจอใช้ไม่ได้เกิน 30 วิ |
| 3 | **แสดงรูปโปรไฟล์ + ชื่อบนจอ scanner** | staff เห็นทันทีว่าคนหน้าไม่ตรง |
| 4 | เตือน "ผู้ที่ให้ QR ผู้อื่นใช้จะถูกตัดสิทธิ์" ในแอป | เชิงจิตวิทยา |

**Rotating code = TOTP**
```python
code = totp(secret=HMAC(TOTP_KEY, ticket_code), period=30, digits=6)
```
- ฝั่ง server ยอมรับ window ±1 (คือ 90 วิ) เผื่อนาฬิกาเครื่องเพี้ยน
- ตั้ง `STRICT_QR_MODE=false` ตอนเริ่ม → ถ้าคิวยาวมากจะได้ปิดได้ทันที
- ⚠️ ถ้าเปิด strict mode ต้องแน่ใจว่า **นาฬิกา scanner sync NTP** ไม่งั้นปฏิเสธทุกคน

---

## 4. Anti-cheat: การโหวต

| ช่องโหว่ | วิธีป้องกัน |
|---|---|
| โหวตซ้ำ | Redis `SET NX` (ด่านหลัก) + Mongo unique `{round_key, user_id}` (ด่านสำรอง) |
| สร้างหลาย account | ผูกกับอีเมลมหาวิทยาลัย + `google_sub` unique → 1 คน 1 อีเมล |
| ยิง API ตรง (ไม่ผ่านหน้าเว็บ) | ไม่เป็นไร ยังโดน dedupe เหมือนกัน — **นี่คือข้อดีของการทำ validation ที่ server** |
| Bot ที่มีอีเมลมหาลัยจริง | rate limit + ตรวจ pattern (โหวตเร็วเกินมนุษย์, User-Agent แปลก) |
| บังคับให้ต้องอยู่ในงาน | ตั้ง `REQUIRE_CHECKIN_TO_VOTE=true` → ต้องเช็คอินก่อน |
| แก้ผลผ่าน DevTools | ผลอยู่ที่ server — client แสดงผลอย่างเดียว |

**Anomaly detection แบบง่าย (รันหลังงาน หรือ realtime ก็ได้):**
```python
# ธงแดง 3 อย่าง
- โหวตภายใน 2 วินาทีหลัง round เปิด        → น่าจะเป็นสคริปต์
- user-agent เดียวกัน + ip_hash เดียวกัน > 50 บัญชี   → farm
- บัญชีที่สร้างวันงาน + โหวตทันที + ไม่เคยเช็คอิน      → บัญชีปลอม
```
เก็บเป็น report ให้ admin ตัดสินใจ **อย่า auto-ban** — false positive ในงานอีเวนต์เจ็บกว่าปล่อยผ่าน

---

## 5. Anti-cheat: คะแนนและ Instagram

| ช่องโหว่ | ป้องกัน |
|---|---|
| ส่งโพสต์เดียวกันซ้ำ | `shortcode` unique index + normalize URL ก่อน (ตัด `?igshid=` ฯลฯ) |
| ส่งโพสต์ของคนอื่น | ตรวจว่า IG handle ในโพสต์ตรงกับที่ผูกไว้ + admin ดูด้วยตา |
| ลบโพสต์หลังได้คะแนน | สุ่มตรวจย้อนหลัง 10% + ตัดคะแนนได้ (ledger รองรับ amount ติดลบ) |
| กด API ให้คะแนนตรงๆ | endpoint ให้คะแนนมีเฉพาะใน `/admin` + role check |
| Staff ปั๊มให้เพื่อน | `audit_logs` ทุก action + `note` บังคับ + **รายงาน "admin ให้คะแนนมากสุด" ทุกวัน** |
| Race condition ตอนอนุมัติ | idempotency_key `ig:{shortcode}:approve` unique → กดรัวก็ได้ครั้งเดียว |

### Insider threat — ที่ทีมส่วนใหญ่มองข้าม
1. แยก role `staff` (สแกนได้อย่างเดียว) ออกจาก `admin` (ให้คะแนนได้) เด็ดขาด
2. `superadmin` มีแค่ 2 คน และ **ไม่ใช่คนที่ลงแข่ง**
3. การปรับคะแนน > 100 แต้ม ต้องมี second approval
4. รายงานสรุปทุกเช้า: ใครให้คะแนนไปเท่าไหร่ ส่งเข้ากลุ่มหัวหน้าทีม
5. Ledger ลบไม่ได้ → ต่อให้ admin โกงก็ตามรอยได้เสมอ

---

## 6. Anti-cheat: วงล้อ

ดู `04-realtime.md` §4 — สรุป:
- ผลตัดสินที่ server ด้วย HMAC ก่อนส่งให้ frontend
- commit hash ประกาศก่อนงาน → พิสูจน์ว่าไม่แก้ผลย้อนหลัง
- reveal server_seed หลังงาน → ทุกคนตรวจสอบเองได้
- `nonce` unique ต่อ user → replay ไม่ได้
- หัก points ก่อนหมุน → หมุนไม่ได้ถ้าเงินไม่พอ

---

## 7. Input validation & injection

FastAPI + Pydantic ตรวจ type ให้อัตโนมัติแล้ว แต่ต้องเพิ่ม:

```python
class VoteIn(BaseModel):
    round_key: str = Field(pattern=r"^[a-z0-9\-]{1,32}$")   # ★ allowlist ไม่ใช่ blocklist
    artist_id: str = Field(pattern=r"^[0-9a-f]{24}$")        # ObjectId format

class IGSubmitIn(BaseModel):
    post_url: HttpUrl
    @field_validator("post_url")
    def must_be_instagram(cls, v):
        if v.host not in ("instagram.com", "www.instagram.com"):
            raise ValueError("ต้องเป็นลิงก์ Instagram เท่านั้น")
        return v
```

**NoSQL injection** — เกิดเมื่อเอา dict จาก user ไปใส่ query ตรงๆ:
```python
# ❌ อันตราย: user ส่ง {"email": {"$ne": null}} → ได้ user คนแรกในระบบ
await db.users.find_one({"email": body["email"]})

# ✅ Pydantic บังคับ type เป็น str แล้ว → ใส่ dict ไม่ได้
class LoginIn(BaseModel):
    email: EmailStr
await db.users.find_one({"email": data.email})
```
กฎเหล็ก: **ห้ามส่ง raw dict จาก request body เข้า Mongo query โดยตรง** ต้องผ่าน Pydantic model เสมอ

---

## 8. Security headers & CORS

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://egoke2026.example"],   # ★ ห้าม ["*"] คู่กับ credentials
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    max_age=600,
)
```
```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options    "nosniff" always;
add_header X-Frame-Options           "DENY" always;
add_header Referrer-Policy           "strict-origin-when-cross-origin" always;
add_header Permissions-Policy        "camera=(self), microphone=(), geolocation=()" always;
add_header Content-Security-Policy   "default-src 'self'; img-src 'self' https: data:; script-src 'self'; connect-src 'self' wss:; frame-ancestors 'none'" always;
```
> `camera=(self)` ต้องเปิด เพราะหน้า scanner ต้องใช้กล้อง

---

## 9. PDPA / ความเป็นส่วนตัว

งานนี้เก็บข้อมูลนักศึกษา → อยู่ใต้ **พ.ร.บ. คุ้มครองข้อมูลส่วนบุคคล (PDPA)**

| ข้อกำหนด | วิธีทำ |
|---|---|
| เก็บเท่าที่จำเป็น | ไม่เก็บเบอร์โทร/ที่อยู่ ถ้าไม่ได้ใช้จริง |
| ขอความยินยอม | หน้า onboarding มี checkbox แยก: ข้อตกลง / ยินยอมให้ถ่ายภาพ |
| แจ้งวัตถุประสงค์ | หน้า Privacy Notice ภาษาไทย ลิงก์จากหน้า login |
| สิทธิเข้าถึง/ลบ | `GET /me/export` (JSON ทั้งหมด) + `DELETE /me` (soft delete) |
| ไม่เก็บ IP ดิบ | เก็บ `sha256(ip + PEPPER)` เท่านั้น |
| ลบเมื่อหมดความจำเป็น | ตั้ง retention 90 วันหลังงาน แล้ว anonymize (แทน email ด้วย hash) |
| Data breach | มีขั้นตอนแจ้ง — ต้องแจ้ง สคส. ภายใน 72 ชม. |

```python
def hash_ip(ip: str) -> str:
    return hashlib.sha256((ip + settings.IP_PEPPER).encode()).hexdigest()
```

**ที่ต้องระวังเป็นพิเศษ:**
- Leaderboard สาธารณะแสดง `display_name` เท่านั้น — **ห้ามแสดงอีเมลหรือรหัสนักศึกษา**
- รูปโปรไฟล์จาก Google ควรให้เลือกได้ว่าจะแสดงไหม
- ภาพจากกล้องหน้างานที่ขึ้นจอ ต้องมีป้ายแจ้ง + ทางเลือกไม่ให้ถ่าย

---

## 10. Secrets ที่ต้องมี

| ตัวแปร | ความยาว | หมุนเวียน |
|---|---|---|
| `JWT_SECRET` | 64 hex | ถ้ารั่ว |
| `QR_SIGNING_KEY` | 64 hex | ถ้ารั่ว (+ bump `qr_version`) |
| `TOTP_KEY` | 64 hex | ถ้ารั่ว |
| `WHEEL_SERVER_SEED` | 64 hex | ทุกวงล้อใหม่ |
| `IP_PEPPER` | 32 hex | ห้ามเปลี่ยน (hash จะไม่ match) |
| `REDIS_PASSWORD` | 32+ | |
| `MONGO_PASSWORD` | 32+ | |
| `GOOGLE_CLIENT_SECRET` | จาก Google | |

```bash
# สร้างครบทุกตัว
for k in JWT_SECRET QR_SIGNING_KEY TOTP_KEY WHEEL_SERVER_SEED; do
  echo "$k=$(openssl rand -hex 32)"
done
echo "IP_PEPPER=$(openssl rand -hex 16)"
```

**เก็บที่ไหน:** GitHub Actions Secrets (สำหรับ CI) + `.env` chmod 600 บนเครื่อง
**ห้าม:** commit เข้า git, ส่งใน Line, ใส่ใน Google Docs ที่แชร์ทั้งทีม

## 11. Pre-event security checklist

- [ ] `nmap -p- <public-ip>` จากเครื่องนอก → เห็นแค่ 22, 80, 443
- [ ] `.env` ไม่อยู่ใน git (`git log --all -- .env` ต้องว่าง)
- [ ] `ENABLE_DOCS=false` ใน production
- [ ] ทดสอบ: login ด้วยอีเมล gmail.com → ต้องโดนปฏิเสธ
- [ ] ทดสอบ: participant เรียก `/admin/*` → ต้องได้ 403
- [ ] ทดสอบ: โหวตซ้ำ 10 ครั้ง → นับแค่ 1
- [ ] ทดสอบ: สแกน QR เดิม 2 ครั้ง → ครั้งที่ 2 = duplicate
- [ ] ทดสอบ: แก้ 1 byte ใน QR payload → invalid_sig
- [ ] SSL Labs score ≥ A
- [ ] ทดสอบ restore backup สำเร็จอย่างน้อย 1 ครั้ง
- [ ] เปลี่ยนรหัสผ่าน default ทุกตัว (Grafana admin/admin!)
