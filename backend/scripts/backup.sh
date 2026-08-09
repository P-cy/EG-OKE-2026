#!/usr/bin/env bash
# สำรองข้อมูล Mongo + Redis
#
#   cd backend && ./scripts/backup.sh              # เก็บลง ./backups/
#   cd backend && ./scripts/backup.sh /mnt/disk2   # เก็บที่อื่น
#
# ★ ทำไมต้องมี: ทั้งระบบอยู่บน VPS เครื่องเดียว ถ้าเครื่องนั้นพัง
#   ข้อมูลผู้เข้างาน 5,000 คน + ประวัติเช็คอิน + ยอดเหรียญ หายทั้งหมด
#   ไม่มีที่ไหนสำรองไว้เลย snapshot ของผู้ให้บริการ VPS ไม่ใช่ backup
#   (มันเป็นภาพของดิสก์ทั้งก้อน กู้ทีต้องกู้ทั้งเครื่อง และมักถ่ายวันละครั้ง)
#
# ★ ระหว่างงาน 3 วัน ควรตั้ง cron ให้รันทุกชั่วโมง:
#     0 * * * * cd /srv/egoke/backend && ./scripts/backup.sh >> /var/log/egoke-backup.log 2>&1
#
# ★ ไฟล์ที่ได้มีข้อมูลส่วนบุคคลทั้งหมด — ปฏิบัติกับมันเหมือนรหัสผ่าน
#   อย่าวางไว้ในโฟลเดอร์ที่ nginx เสิร์ฟ อย่าอัปขึ้น Google Drive ที่แชร์ทั้งทีม

set -euo pipefail
cd "$(dirname "$0")/.."

DEST="${1:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
ENV_FILE=".env.production"
STAMP="$(date +%Y%m%d-%H%M%S)"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE")

[ -f "$ENV_FILE" ] || { echo "ไม่เจอ $ENV_FILE"; exit 1; }
# shellcheck disable=SC1090
set -a; . "./$ENV_FILE"; set +a

mkdir -p "$DEST"
chmod 700 "$DEST"

# ── Mongo ──────────────────────────────────────────────────────────────
# --archive --gzip ได้ไฟล์เดียวจบ กู้ด้วย mongorestore --archive --gzip
echo "[1/3] mongodump"
"${COMPOSE[@]}" exec -T mongo mongodump \
  --username "$MONGO_ROOT_USER" --password "$MONGO_ROOT_PASSWORD" \
  --authenticationDatabase admin \
  --db "$MONGO_DB" --archive --gzip > "$DEST/mongo-$STAMP.archive.gz"

# ── Redis ──────────────────────────────────────────────────────────────
# ★ ไม่ใช่ cache ที่ทิ้งได้ — มันถือคะแนนโหวตสด กันเช็คอินซ้ำ และโควตาจ่ายเหรียญ
#   BGSAVE เขียน dump.rdb ใหม่แบบไม่บล็อกการทำงาน แล้วค่อยคัดลอกออกมา
echo "[2/3] redis BGSAVE"
LAST="$("${COMPOSE[@]}" exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning LASTSAVE | tr -d '\r')"
"${COMPOSE[@]}" exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning BGSAVE >/dev/null

# รอจนกว่า LASTSAVE จะขยับ = snapshot ใหม่เขียนเสร็จจริง
# (ถ้าคัดลอกทันทีจะได้ dump.rdb ของรอบก่อน ซึ่งดูเหมือนสำเร็จแต่ข้อมูลเก่า)
for _ in $(seq 1 60); do
  NOW="$("${COMPOSE[@]}" exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning LASTSAVE | tr -d '\r')"
  [ "$NOW" != "$LAST" ] && break
  sleep 1
done
[ "$NOW" != "$LAST" ] || { echo "  [เตือน] redis BGSAVE ไม่เสร็จใน 60 วิ — ไฟล์ที่ได้อาจเป็นของรอบก่อน"; }

CID="$("${COMPOSE[@]}" ps -q redis)"
docker cp "$CID:/data/dump.rdb" "$DEST/redis-$STAMP.rdb"
gzip -f "$DEST/redis-$STAMP.rdb"

# ── ล้างของเก่า ────────────────────────────────────────────────────────
echo "[3/3] ลบ backup ที่เก่ากว่า $KEEP_DAYS วัน"
find "$DEST" -name 'mongo-*.archive.gz' -mtime "+$KEEP_DAYS" -delete
find "$DEST" -name 'redis-*.rdb.gz'     -mtime "+$KEEP_DAYS" -delete

chmod 600 "$DEST"/*.gz 2>/dev/null || true

echo ""
echo "เสร็จ:"
ls -lh "$DEST" | grep "$STAMP" || true
echo ""
echo "★ backup ที่อยู่บนเครื่องเดียวกับของจริงไม่นับเป็น backup —"
echo "  ดึงออกไปเก็บที่อื่นด้วย เช่น:  scp $DEST/*-$STAMP.* you@another-host:~/egoke-backups/"
echo ""
echo "วิธีกู้:"
echo "  mongo: docker compose -f docker-compose.prod.yml exec -T mongo mongorestore \\"
echo "           -u \$MONGO_ROOT_USER -p \$MONGO_ROOT_PASSWORD --authenticationDatabase admin \\"
echo "           --archive --gzip --drop < $DEST/mongo-$STAMP.archive.gz"
echo "  redis: หยุด container -> วาง dump.rdb ที่ /data -> start ใหม่"
