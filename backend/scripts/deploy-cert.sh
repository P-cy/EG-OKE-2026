#!/usr/bin/env bash
# ขอใบรับรอง TLS จาก Let's Encrypt แล้วเปิด nginx
#
#   cd backend && ./scripts/deploy-cert.sh              # ของจริง
#   cd backend && ./scripts/deploy-cert.sh --staging    # ซ้อมก่อน (ไม่กิน quota)
#
# ★ ทำไมต้องมีสคริปต์นี้ ไม่ใช่แค่ `docker compose up`:
#   nginx ไม่ยอมสตาร์ทถ้าหาไฟล์ใบรับรองไม่เจอ แต่ certbot ต้องใช้ nginx
#   เสิร์ฟ /.well-known/acme-challenge/ เพื่อพิสูจน์ว่าเราคุมโดเมนนี้จริง
#   → ไก่กับไข่ สคริปต์นี้แก้ด้วยการวางใบรับรองปลอมให้ nginx บูตได้ก่อน
#     แล้วค่อยลบทิ้งแล้วขอใบจริงทับ
#
# ★ --staging ใช้ตอนซ้อม: Let's Encrypt จำกัดความล้มเหลว 5 ครั้ง/ชม./โดเมน
#   ถ้า DNS ยังไม่ชี้มาแล้วยิงของจริงรัวๆ จะโดนแบนโดเมนนั้นข้ามชั่วโมง

set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=".env.production"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE")

[ -f "$ENV_FILE" ] || { echo "ไม่เจอ $ENV_FILE — รัน ./scripts/deploy-init.sh ก่อน"; exit 1; }

# shellcheck disable=SC1090
set -a; . "./$ENV_FILE"; set +a

for v in API_DOMAIN APP_DOMAIN CERTBOT_EMAIL; do
  [ -n "${!v:-}" ] || { echo "$v ยังว่างใน $ENV_FILE"; exit 1; }
done

STAGING_ARG=""
if [ "${1:-}" = "--staging" ]; then
  STAGING_ARG="--staging"
  echo "โหมดซ้อม — ใบรับรองที่ได้เบราว์เซอร์จะขึ้นเตือน (ปกติ)"
fi

echo "โดเมน: $API_DOMAIN , $APP_DOMAIN"

# ── 0. เช็ค DNS ก่อน จะได้ไม่เสีย quota ไปเปล่าๆ ──────────────────────
MY_IP="$(curl -fsS --max-time 5 https://api.ipify.org || echo '')"
for d in "$API_DOMAIN" "$APP_DOMAIN"; do
  # getent มีบน Linux, dig/host มีบน mac — ลองไล่ไปจนกว่าจะมีตัวที่ใช้ได้
  RESOLVED="$( { getent hosts "$d" 2>/dev/null | awk '{print $1}'; } \
             || dig +short "$d" 2>/dev/null \
             || true )"
  RESOLVED="$(printf '%s\n' "$RESOLVED" | head -1)"
  if [ -z "$RESOLVED" ]; then
    echo "  [เตือน] $d ยังหาไม่เจอใน DNS — ตั้ง A record ชี้มาที่ ${MY_IP:-IP ของ VPS} ก่อน"
  elif [ -n "$MY_IP" ] && [ "$RESOLVED" != "$MY_IP" ]; then
    echo "  [เตือน] $d ชี้ไปที่ $RESOLVED แต่เครื่องนี้คือ $MY_IP"
    echo "          (ถ้าใช้ Cloudflare proxy (เมฆส้ม) อันนี้ปกติ — ปิด proxy ชั่วคราวตอนขอใบรับรอง)"
  else
    echo "  [ok] $d -> $RESOLVED"
  fi
done

# ── 1. ใบรับรองปลอม เพื่อให้ nginx บูตขึ้นมาได้ก่อน ────────────────────
CERT_PATH="/etc/letsencrypt/live/$API_DOMAIN"
echo ""
echo "[1/5] วางใบรับรองชั่วคราว"
"${COMPOSE[@]}" run --rm --entrypoint sh certbot -c "
  mkdir -p '$CERT_PATH' &&
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout '$CERT_PATH/privkey.pem' -out '$CERT_PATH/fullchain.pem' \
    -subj '/CN=localhost' 2>/dev/null
"

# ── 2. เปิด nginx (ตอนนี้บูตขึ้นแล้วเพราะมีไฟล์ใบรับรอง) ───────────────
echo "[2/5] เปิด nginx"
"${COMPOSE[@]}" up -d nginx
sleep 3

# ── 3. ทิ้งใบปลอม ──────────────────────────────────────────────────────
# ★ ต้องลบก่อนขอใบจริง ไม่งั้น certbot เห็นว่า live/<domain> ไม่ว่าง
#   แล้วไปสร้าง live/<domain>-0001 แทน ซึ่ง nginx ไม่ได้ชี้ไปที่นั่น
#   → ได้ใบจริงมาแต่เว็บยังใช้ใบปลอมอยู่ หาสาเหตุยากมาก
#   (nginx ที่รันอยู่ยังเสิร์ฟได้ต่อ เพราะมันอ่านใบรับรองเข้าหน่วยความจำไปแล้ว)
echo "[3/5] ลบใบชั่วคราว"
"${COMPOSE[@]}" run --rm --entrypoint sh certbot -c "
  rm -rf '/etc/letsencrypt/live/$API_DOMAIN' \
         '/etc/letsencrypt/archive/$API_DOMAIN' \
         '/etc/letsencrypt/renewal/$API_DOMAIN.conf'
"

# ── 4. ขอใบจริง — ใบเดียวคลุมทั้งสองโดเมน ─────────────────────────────
# เก็บไว้ใต้ชื่อ $API_DOMAIN (--cert-name) เพราะ nginx ทั้งสอง server block
# ชี้มาที่ path เดียวกัน ถ้าปล่อยให้ certbot ตั้งชื่อเอง path จะไม่ตรง
echo "[4/5] ขอใบรับรองจาก Let's Encrypt"
"${COMPOSE[@]}" run --rm --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot \
  --cert-name "$API_DOMAIN" \
  -d "$API_DOMAIN" -d "$APP_DOMAIN" \
  --email "$CERTBOT_EMAIL" --agree-tos --no-eff-email \
  --non-interactive $STAGING_ARG

# ── 5. reload ให้ nginx หยิบใบจริงไปใช้ ────────────────────────────────
echo "[5/5] reload nginx"
"${COMPOSE[@]}" exec nginx nginx -s reload

echo ""
echo "เสร็จแล้ว ลองเปิด: https://$API_DOMAIN/healthz"
echo "ใบรับรองต่ออายุเองอัตโนมัติ (container ชื่อ certbot เช็คทุก 12 ชม.)"
