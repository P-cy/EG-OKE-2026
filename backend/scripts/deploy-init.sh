#!/usr/bin/env bash
# สร้าง secret ทั้งหมดสำหรับ production + mongo keyfile
#
#   cd backend && ./scripts/deploy-init.sh
#
# รันซ้ำได้ปลอดภัย — เติมเฉพาะช่องที่ยังว่าง ไม่แตะค่าที่กรอกไว้แล้ว
# (สำคัญ: IP_PEPPER กับ QR_SIGNING_KEY ถ้าถูกเปลี่ยนหลังเปิดใช้งานจริง
#  บัตร QR ที่แจกไปแล้วจะใช้ไม่ได้ทั้งหมด)

set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=".env.production"
KEYFILE="secrets/mongo-keyfile"
MONGO_UID=999   # uid ของ user "mongodb" ใน image mongo:7

say()  { printf '%s\n' "$*"; }
ok()   { printf '  [ok]   %s\n' "$*"; }
warn() { printf '  [ดู]   %s\n' "$*"; }

# ── 1. ไฟล์ env ────────────────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  cp .env.production.example "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  say "สร้าง $ENV_FILE จาก template แล้ว"
fi

# เติมค่าเฉพาะบรรทัดที่เป็น "KEY=" เปล่าๆ เท่านั้น
#
# ★ ต้องเช็คให้แน่ว่าบรรทัดนั้น "ว่างจริง" ไม่ใช่แค่ดูเหมือนว่าง —
#   เวอร์ชันแรกใช้ regex ^KEY=\s*$ ซึ่งไม่ match บรรทัดที่มี comment ต่อท้าย
#   (KEY=      # อธิบาย) ผลคือสคริปต์รายงาน "มีค่าอยู่แล้ว ไม่แตะ" ทุกตัว
#   แล้วจบสวยๆ ทั้งที่ไม่ได้สร้าง secret อะไรเลยสักตัว — พังแบบเงียบสนิท
#   ตอนนี้ template ไม่มี comment ต่อท้ายค่าแล้ว แต่ยังกันไว้เผื่อคนมาแก้ทีหลัง
fill() {
  local key="$1" val="$2"
  local cur
  cur="$(grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2- | sed -E 's/[[:space:]]*#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//')"
  if [ -n "$cur" ]; then
    warn "$key มีค่าอยู่แล้ว — ไม่แตะ"
    return
  fi
  # ใช้ | เป็นตัวคั่นของ sed — ค่า hex ไม่มี | แน่นอน
  sed -i.bak -E "s|^${key}=.*$|${key}=${val}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
  ok "$key สร้างใหม่แล้ว"
}

say ""
say "── secret ──"
fill MONGO_ROOT_PASSWORD "$(openssl rand -hex 24)"   # hex ล้วน: ปลอดภัยเวลาเอาไปต่อใน MONGO_URI
fill REDIS_PASSWORD      "$(openssl rand -hex 24)"
fill JWT_SECRET          "$(openssl rand -hex 32)"
fill QR_SIGNING_KEY      "$(openssl rand -hex 32)"
fill TOTP_KEY            "$(openssl rand -hex 32)"
fill WHEEL_SERVER_SEED   "$(openssl rand -hex 32)"
fill IP_PEPPER           "$(openssl rand -hex 16)"
fill DISPLAY_TOKEN       "$(openssl rand -hex 32)"

# ── 2. mongo keyfile ───────────────────────────────────────────────────
# replica set + access control ต้องมาคู่กัน: สมาชิกในเซ็ตยืนยันตัวตนกันเอง
# ด้วย keyfile นี้ ต่อให้มีสมาชิกเดียวก็ยังต้องมี ไม่งั้น mongod ไม่ยอมบูต
say ""
say "── mongo keyfile ──"
mkdir -p secrets
if [ -f "$KEYFILE" ]; then
  warn "$KEYFILE มีอยู่แล้ว — ไม่สร้างใหม่ (สร้างใหม่ = ข้อมูลเดิมเข้าไม่ได้)"
else
  openssl rand -base64 756 > "$KEYFILE"
  ok "สร้าง $KEYFILE แล้ว"
fi

# ★ mongod ปฏิเสธ keyfile ที่คนอื่นอ่านได้ และต้องเป็นเจ้าของไฟล์เอง
#   ถ้าข้ามขั้นนี้ mongo จะขึ้น "permissions on keyfile are too open" แล้วตายทันที
chmod 400 "$KEYFILE"
if [ "$(id -u)" = "0" ]; then
  chown "$MONGO_UID:$MONGO_UID" "$KEYFILE"; ok "chown $MONGO_UID เรียบร้อย"
elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  sudo chown "$MONGO_UID:$MONGO_UID" "$KEYFILE"; ok "chown $MONGO_UID เรียบร้อย (ผ่าน sudo)"
else
  warn "chown ไม่ได้ — ถ้า mongo บูตไม่ขึ้น ให้รัน: sudo chown $MONGO_UID:$MONGO_UID $KEYFILE"
  warn "(บน macOS/Docker Desktop ข้ามได้ ownership ถูกจำลองให้อยู่แล้ว)"
fi

# ── 3. เช็คว่าอะไรยังต้องกรอกเอง ───────────────────────────────────────
say ""
say "── ค่าที่สคริปต์สร้างแทนไม่ได้ ต้องกรอกเอง ──"
missing=0
check() {
  local key="$1" hint="$2"
  local cur
  cur="$(grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2- | sed -E 's/[[:space:]]*#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//')"
  # CHANGE_ME คือค่าตัวอย่างใน template — ต้องนับว่า "ยังไม่ได้กรอก"
  # ไม่งั้นจะรายงานผ่านทั้งที่ค่ายังเป็นโดเมนสมมติ แล้วไปพังตอนขอใบรับรอง
  case "$cur" in
    ""|*CHANGE_ME*)
      printf '  [ยังว่าง] %-22s %s\n' "$key" "$hint"; missing=$((missing+1)) ;;
    *) ok "$key = $cur" ;;
  esac
}
check API_DOMAIN           "โดเมนของ API เช่น api.egoke2026.com (ต้องชี้ A record มาที่ IP ของ VPS แล้ว)"
check APP_DOMAIN           "โดเมนหน้าเว็บ — ★ ต้องเป็นโดเมนจดทะเบียนเดียวกับ API"
check FRONTEND_ORIGIN      "https:// + APP_DOMAIN — ไม่ตรง = CORS บล็อกทุก request"
check API_BASE_URL         "https:// + API_DOMAIN"
check GOOGLE_REDIRECT_URI  "https:// + APP_DOMAIN + /login — ต้องตรงกับ Google Console เป๊ะ"
check CERTBOT_EMAIL        "อีเมลรับแจ้งเตือนใบรับรองใกล้หมดอายุ"
check GOOGLE_CLIENT_ID     "จาก Google Cloud Console > Credentials"
check GOOGLE_CLIENT_SECRET "จาก Google Cloud Console > Credentials"
check ADMIN_EMAILS         "อีเมลที่จะได้เป็น admin อัตโนมัติตอน login"

say ""
if [ "$missing" -gt 0 ]; then
  say "เหลืออีก $missing ค่า — แก้ใน $ENV_FILE แล้วค่อยไปต่อ"
  say "แล้วรัน: ./scripts/deploy-cert.sh"
else
  say "ครบแล้ว — ต่อด้วย: ./scripts/deploy-cert.sh"
fi
