# 05 — Infrastructure, Deployment & Disaster Recovery

> ★ **เอกสารนี้เป็นแผนตอนออกแบบ ไม่ใช่ของที่ทำจริง**
>
> ที่เขียนไว้เป็นสถาปัตยกรรม 3 เครื่อง (app-1 / app-2 / ops) พร้อม replica set
> ข้ามเครื่องและ arbiter ซึ่งเกินความจำเป็นสำหรับงานนี้มาก
>
> **ของที่ทำจริงและทดสอบแล้วอยู่ที่ [14-deploy-vps.md](14-deploy-vps.md)** — VPS เครื่องเดียว
> พร้อมสคริปต์ `deploy-init.sh` / `deploy-cert.sh` / `backup.sh` และ
> `backend/docker-compose.prod.yml`
>
> เก็บไฟล์นี้ไว้เป็นข้อมูลอ้างอิงกรณีต้องขยายทีหลัง — snippet ในนี้ (โดยเฉพาะ
> docker-compose กับ nginx) **ล้าสมัยแล้ว** อย่าคัดลอกไปใช้

## 1. Server fleet (Contabo)

| Node | สเปก | แผน | บทบาท |
|---|---|---|---|
| **app-1** (primary) | 8 vCPU / 24 GB / 200 GB NVMe | Cloud VPS 30 | Nginx, FastAPI ×4, ws ×2, worker ×2, broadcaster, **Mongo PRIMARY**, **Redis master** |
| **app-2** (standby) | 6 vCPU / 12 GB / 100 GB NVMe | Cloud VPS 20 | Nginx (warm), FastAPI ×2 (idle), **Mongo SECONDARY**, **Redis replica** |
| **ops** | 3 vCPU / 8 GB / 75 GB NVMe | Cloud VPS 10 | **Mongo ARBITER**, Prometheus, Grafana, Loki, Uptime Kuma, backup runner, staging env |

> **วางคนละ region:** app-1 = EU (Nuremberg) หรือ Singapore, app-2 = คนละ datacenter
> **แนะนำ Singapore** สำหรับงานในไทย — latency ~30-50ms vs EU ~180-250ms
> latency 200ms ต่อ request ทำให้หน้าเว็บรู้สึกหน่วงมากตอนสแกน QR

### ทำไมต้อง arbiter บน ops
MongoDB replica set ต้องมีสมาชิกเลขคี่เพื่อโหวตเลือก primary
2 nodes = ถ้าเครื่องนึงตาย อีกเครื่องโหวตคนเดียวไม่ได้ → **ไม่มี primary → เขียนไม่ได้เลย**
Arbiter กินทรัพยากรแทบเป็นศูนย์ (ไม่เก็บข้อมูล) แต่ทำให้ failover อัตโนมัติทำงานได้

## 2. Cloudflare (Free plan)

```
DNS:
  egoke2026.example       A  app-1  (proxied 🟠, TTL 60)
  api.egoke2026.example   A  app-1  (proxied 🟠, TTL 60)
  ops.egoke2026.example   A  ops    (DNS only, ปิดด้วย Cloudflare Access)
```

ตั้งค่าที่ต้องเปิด:
| ฟีเจอร์ | ค่า | เหตุผล |
|---|---|---|
| SSL/TLS mode | Full (strict) | end-to-end encryption |
| Always Use HTTPS | on | |
| Auto Minify + Brotli | on | ลด payload |
| Bot Fight Mode | on | กัน scraper |
| Cache Rule: `/live/*` | Cache Everything, Edge TTL 2s | ★ ตัวนี้คือตัวรอด |
| Cache Rule: `/v1/auth/*`, `/v1/admin/*` | Bypass | ห้าม cache ของส่วนตัวเด็ดขาด |
| Rate Limiting Rule | 300 req/นาที/IP → challenge | ชั้นนอกสุด |
| Page Rule: `/admin*` | Cloudflare Access (email OTP) | admin ไม่ควรเปิดสาธารณะ |

**สิ่งที่ห้ามลืม:** ตั้ง Cache Rule ให้ **`Cache Everything` มีผลเฉพาะ `/live/*`** ถ้าตั้งกว้างเกินไปแล้ว cache หน้า `/me` ของคนหนึ่งไปให้อีกคน = ข้อมูลส่วนตัวรั่ว

## 3. Docker Compose (app-1)

```yaml
# docker-compose.prod.yml — ตัวเต็มอยู่ใน backend/
services:
  nginx:
    image: nginx:1.27-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
      - nginx_cache:/var/cache/nginx
    depends_on: [api, ws]
    restart: unless-stopped

  api:
    image: ghcr.io/egoke/backend:${TAG}
    command: gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4
             --bind 0.0.0.0:8000 --max-requests 10000 --max-requests-jitter 1000
             --timeout 30 --graceful-timeout 20
    env_file: .env
    deploy: { resources: { limits: { cpus: "4.0", memory: 4G } } }
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/readyz"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 20s
    restart: unless-stopped

  ws:
    image: ghcr.io/egoke/backend:${TAG}
    command: uvicorn app.ws_main:app --host 0.0.0.0 --port 8001 --workers 2
    env_file: .env
    deploy: { resources: { limits: { cpus: "1.5", memory: 1G } } }
    restart: unless-stopped

  worker:
    image: ghcr.io/egoke/backend:${TAG}
    command: python -m app.workers.runner
    env_file: .env
    deploy: { replicas: 2, resources: { limits: { cpus: "1.0", memory: 1G } } }
    restart: unless-stopped

  broadcaster:
    image: ghcr.io/egoke/backend:${TAG}
    command: python -m app.workers.broadcaster
    env_file: .env
    deploy: { replicas: 1 }          # ★ ต้อง 1 เท่านั้น
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: >
      redis-server
      --appendonly yes --appendfsync everysec
      --maxmemory 3gb --maxmemory-policy noeviction
      --save 900 1 --save 300 10
      --requirepass ${REDIS_PASSWORD}
    volumes: [redis_data:/data]
    deploy: { resources: { limits: { memory: 4G } } }
    restart: unless-stopped

  mongo:
    image: mongo:7
    command: >
      mongod --replSet rs0 --bind_ip_all --keyFile /etc/mongo/keyfile
             --wiredTigerCacheSizeGB 8
    volumes:
      - mongo_data:/data/db
      - ./mongo/keyfile:/etc/mongo/keyfile:ro
    deploy: { resources: { limits: { memory: 12G } } }
    restart: unless-stopped

volumes: { redis_data:, mongo_data:, nginx_cache: }
```

### ค่าที่สำคัญและทำไม
| ค่า | เหตุผล |
|---|---|
| `--max-requests 10000 --jitter 1000` | รีไซเคิล worker กัน memory leak สะสม 3 วัน; jitter กัน restart พร้อมกัน |
| `--graceful-timeout 20` | ให้ request ที่ค้างอยู่เสร็จก่อนตาย ไม่ตัดกลางคัน |
| Redis `appendfsync everysec` | เสียข้อมูลได้มากสุด 1 วินาที — ยอมรับได้, เร็วกว่า `always` มาก |
| Redis `maxmemory-policy noeviction` | ★ **ห้ามใช้ `allkeys-lru`** ไม่งั้น Redis จะลบ dedupe key ทิ้งเงียบๆ = โหวตซ้ำได้ |
| `wiredTigerCacheSizeGB 8` | dataset < 100MB → 8GB เกินพอมาก, กันไม่ให้ Mongo กิน RAM หมดเครื่อง |

## 4. Nginx config (จุดที่สำคัญ)

```nginx
# --- Rate limiting zones ---
limit_req_zone  $binary_remote_addr zone=general:10m rate=100r/m;
limit_req_zone  $binary_remote_addr zone=auth:5m     rate=10r/m;
limit_conn_zone $binary_remote_addr zone=perip:10m;

# --- Micro-cache สำหรับ live endpoints ---
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=live:20m
                 max_size=200m inactive=60s use_temp_path=off;

upstream api { server api:8000 max_fails=3 fail_timeout=10s; keepalive 64; }
upstream ws  { server ws:8001;  keepalive 32; }

server {
  listen 443 ssl http2;
  server_name api.egoke2026.example;

  client_max_body_size 5m;         # จำกัดขนาด upload
  limit_conn perip 40;

  # ★ จุดที่ทำให้ 2,000 คน poll พร้อมกันแล้วไม่ล่ม
  location /v1/live/ {
    proxy_cache            live;
    proxy_cache_valid 200  1s;
    proxy_cache_lock       on;              # cache miss พร้อมกัน → upstream เห็นแค่ 1
    proxy_cache_lock_timeout 2s;
    proxy_cache_use_stale  updating error timeout http_500 http_502 http_503;
    proxy_cache_background_update on;       # เสิร์ฟของเก่าไปก่อน แล้วอัปเดตเบื้องหลัง
    add_header X-Cache-Status $upstream_cache_status;
    proxy_pass http://api;
  }

  location /v1/auth/ {
    limit_req zone=auth burst=5 nodelay;
    proxy_pass http://api;
  }

  location /v1/live/ws {
    proxy_pass http://ws;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 300s;                # ★ default 60s จะตัด WS ทิ้ง
    proxy_send_timeout 300s;
  }

  location /v1/ {
    limit_req zone=general burst=20 nodelay;
    proxy_pass http://api;
    proxy_set_header X-Real-IP        $remote_addr;
    proxy_set_header X-Forwarded-For  $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 3s;
    proxy_read_timeout    30s;
    proxy_next_upstream   error timeout http_502 http_503;
  }
}
```

> `burst=20 nodelay` แปลว่า: อนุญาตให้พุ่งได้ 20 request ทันทีโดยไม่หน่วง แล้วค่อยจำกัดตาม rate
> ถ้าไม่ใส่ `nodelay` Nginx จะหน่วง request ให้ตรง rate = ผู้ใช้รู้สึกว่าเว็บช้า

## 5. Deployment pipeline

```
push tag v1.2.3
   │
   ├─ GitHub Actions
   │    ├─ ruff + mypy
   │    ├─ pytest (unit + integration ด้วย mongodb-memory + fakeredis)
   │    ├─ docker build --platform linux/amd64
   │    └─ push ghcr.io/egoke/backend:v1.2.3
   │
   ├─ deploy staging (ops) → smoke test อัตโนมัติ
   │
   └─ manual approve → deploy app-2 → verify → deploy app-1
```

### Zero-downtime deploy (rolling)
```bash
# บน app-1
docker compose pull api
docker compose up -d --no-deps --scale api=8 api    # ขึ้นตัวใหม่ 4 ตัว รวมเป็น 8
sleep 25                                            # รอ healthcheck ผ่าน
docker compose up -d --no-deps --scale api=4 api    # ลดกลับ 4 (ตัวเก่าถูกฆ่า)
```
Nginx `max_fails=3 fail_timeout=10s` จะเลี่ยง instance ที่ยังไม่พร้อมเอง

**ห้าม deploy ระหว่างงาน** ยกเว้น hotfix ที่ P0 — ตั้ง freeze window ไว้เลย

## 6. Backup strategy

| ชนิด | ความถี่ | เก็บที่ | เก็บนาน |
|---|---|---|---|
| Mongo secondary (live replica) | realtime | app-2 | ตลอด |
| `mongodump` เต็ม | ทุก 6 ชม. (ปกติ) / **ทุก 30 นาที (ช่วงงาน)** | ops → Contabo Object Storage | 30 วัน |
| Redis RDB/AOF | ทุก 5 นาที | app-1 local + rsync ไป ops | 7 วัน |
| Oplog tail | ต่อเนื่อง | ops | 3 วัน (point-in-time recovery) |
| Object Storage (รูป IG) | versioning เปิด | Contabo S3 | ตลอด |

```bash
#!/usr/bin/env bash
# /opt/egoke/backup.sh — cron: */30 * * * *  ช่วงงาน
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT=/tmp/dump-$TS

mongodump --uri="$MONGO_URI" --oplog --gzip --archive=$OUT.gz
aws s3 cp $OUT.gz s3://egoke-backup/mongo/$TS.gz --endpoint-url $S3_ENDPOINT
redis-cli -a "$REDIS_PASSWORD" --rdb /tmp/redis-$TS.rdb
aws s3 cp /tmp/redis-$TS.rdb s3://egoke-backup/redis/$TS.rdb --endpoint-url $S3_ENDPOINT
rm -f $OUT.gz /tmp/redis-$TS.rdb
curl -fsS "$HEALTHCHECK_PING_URL"     # ★ dead-man switch: ไม่ ping = ได้ alert
```

> **`curl $HEALTHCHECK_PING_URL` สำคัญที่สุดในสคริปต์นี้** — backup ที่เงียบๆ ไม่ทำงานมา 2 สัปดาห์
> คือสิ่งที่คนค้นพบตอนต้องกู้ข้อมูลพอดี ใช้ healthchecks.io (ฟรี)

### ⚠️ กฎที่ต้องทำจริง: ทดสอบ restore
```bash
# บน ops, อย่างน้อย 1 ครั้ง/สัปดาห์ ก่อนงาน
mongorestore --uri="mongodb://localhost:27018" --gzip --archive=latest.gz --drop
python -m app.scripts.verify_restore    # นับ document ทุก collection เทียบ production
```
**backup ที่ไม่เคยทดสอบ restore = ไม่มี backup**

## 7. Failover runbook

### กรณี A: Mongo primary ล่ม (อัตโนมัติ)
```
app-1 mongod ตาย
  → arbiter + app-2 โหวต → app-2 กลายเป็น primary  [~10-15 วิ]
  → driver อ่าน replicaSet topology ใหม่ ต่อไป app-2 เอง  [อัตโนมัติ]
  → ระหว่างนั้น: write ล้มเหลว 10-15 วิ แต่ vote/checkin ยังเข้า Redis stream ได้ปกติ
```
**ไม่ต้องทำอะไร** ตราบใดที่ connection string ระบุครบทุก host:
```
mongodb://app-1:27017,app-2:27017/egoke2026?replicaSet=rs0&retryWrites=true&w=majority
```

### กรณี B: app-1 ทั้งเครื่องล่ม (ต้องกดเอง, target < 5 นาที)
```
[0:00] Uptime Kuma ยิง alert เข้า Line Notify + Discord
[0:30] ยืนยันว่าล่มจริง (ลอง ssh, ping)
[1:00] Cloudflare Dashboard → เปลี่ยน A record ของ api + www → IP ของ app-2
       (TTL 60 + proxied → มีผลภายใน ~60 วิ)
[1:30] ssh app-2 && cd /opt/egoke && ./promote-to-primary.sh
        ├─ rs.stepDown() ที่ node เดิม (ถ้าเข้าถึงได้) หรือ rs.reconfig({force:true})
        ├─ redis-cli REPLICAOF NO ONE          # promote redis เป็น master
        ├─ docker compose up -d --scale api=4 --scale ws=2 worker broadcaster
        └─ ตรวจ /readyz
[3:00] ตรวจ smoke test: login / snapshot / checkin
[4:00] ประกาศในกลุ่ม staff ว่ากลับมาแล้ว
```
**ซ้อมจริงอย่างน้อย 2 ครั้ง** ก่อนวันงาน จับเวลาด้วย ถ้าเกิน 5 นาทีแปลว่ายังไม่พร้อม

### กรณี C: Redis ล่ม (เจ็บที่สุด)
Redis คือ single point of failure ของ design นี้ ทางลด:
1. AOF `everysec` + RDB → restart แล้วกู้ได้เกือบหมด
2. `replicaof` ที่ app-2 → promote ได้ใน ~30 วิ
3. **Redis Sentinel 3 nodes** (app-1, app-2, ops) → failover อัตโนมัติ **← แนะนำถ้ามีเวลา setup**
4. Warm-up script: rebuild `tally:*` จาก `votes`, `lb:points` จาก `point_transactions` — เขียนไว้ล่วงหน้าและทดสอบแล้ว

### กรณี D: อินเทอร์เน็ตหน้างานล่ม
| ระบบ | แผนสำรอง |
|---|---|
| สแกน QR | ✅ scanner ตรวจ HMAC ได้ offline → คิวใน IndexedDB → sync ทีหลัง |
| จอแสดงผล | ✅ cache snapshot ล่าสุด + ขึ้นป้าย "ข้อมูล ณ 20:14" |
| โหวต | ❌ ต้องมีเน็ต → เตรียม 4G router สำรอง + tethering มือถือ staff |
| วงล้อ | ⚠️ มี local mode ให้ operator กดผลเองแล้ว sync ทีหลัง (บันทึกใน audit log) |

**เตรียม 4G/5G router สำรอง 2 ตัว คนละเครือข่าย** (AIS + True) — ค่านี้ไม่ได้อยู่ในงบ server แต่สำคัญกว่า

## 8. Monitoring & Alerting

### Stack (บน ops)
- **Prometheus** — scrape `/metrics` ทุก 15 วิ
- **Grafana** — dashboard
- **Loki + Promtail** — log รวมศูนย์ (structured JSON)
- **Uptime Kuma** — probe จากภายนอก ทุก 30 วิ → Line Notify / Discord webhook
- **Sentry** (free tier) — error tracking + stack trace

### Metric ที่ต้องมี dashboard
```
egoke_http_requests_total{route,method,status}
egoke_http_duration_seconds{route}           → p50 / p95 / p99
egoke_votes_accepted_total{round_key}
egoke_vote_stream_lag                        ★ ตัวชี้ว่า worker ตามทันไหม
egoke_checkins_total{result,gate}
egoke_ws_connections_active
egoke_redis_latency_seconds
egoke_mongo_pool_in_use / _available
egoke_points_ledger_drift                    ★ balance ไม่ตรง ledger กี่คน
```

### Alert rules
| Alert | เงื่อนไข | ความรุนแรง |
|---|---|---|
| API 5xx สูง | `rate(5xx) > 1%` 2 นาที | 🔴 P1 |
| p99 latency | `> 1s` 3 นาที | 🟠 P2 |
| Vote stream lag | `> 5000` ข้อความ | 🔴 P1 (worker ตายหรือ Mongo ล่ม) |
| Mongo replica lag | `> 10s` | 🟠 P2 |
| Redis memory | `> 80%` | 🟠 P2 |
| Disk | `> 85%` | 🟠 P2 |
| Backup ไม่มา | ไม่ ping 45 นาที | 🔴 P1 |
| Points drift | `> 0` | 🟠 P2 |

### War room หน้างาน (สำคัญมาก)
- จอ Grafana 1 จอ **ตั้งให้ทีมเห็นตลอดเวลา** ในห้อง control
- คนเวร on-call 1 คนต่อกะ ไม่ทำอย่างอื่น
- กลุ่ม Line/Discord แยกสำหรับ incident เท่านั้น
- แปะ **runbook พิมพ์ออกกระดาษ** ไว้ในห้อง (เพราะถ้าเน็ตล่มจะเปิด Notion ไม่ได้)

## 9. Security hardening

```bash
# ทุกเครื่อง
ufw default deny incoming && ufw allow 22,80,443/tcp && ufw enable
# ★ Mongo/Redis เปิดเฉพาะ private network ระหว่างโหนดเท่านั้น
ufw allow from <app-2-private-ip> to any port 27017,6379 proto tcp

# SSH
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/'  /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart sshd

apt install -y fail2ban unattended-upgrades
```

**ต้องทำ:**
- Mongo/Redis **ห้าม bind 0.0.0.0 บน public interface** — ใช้ Contabo private network หรือ WireGuard mesh
- Mongo เปิด auth + keyFile · Redis ตั้ง `requirepass` ยาว 32+ ตัว
- `.env` chmod 600, ไม่เข้า git, secrets เก็บใน GitHub Actions Secrets
- Let's Encrypt auto-renew (certbot systemd timer) + ทดสอบ renew ก่อนงาน
- ต่อ Mongo/Redis ข้ามเครื่องผ่าน **WireGuard** ถ้า Contabo private network ไม่พร้อม

> ⚠️ Redis ที่เปิด public โดยไม่มีรหัสผ่านคือช่องโหว่ที่ถูกสแกนเจอภายใน **ไม่กี่นาที** — ตรวจซ้ำด้วย `nmap -p6379,27017 <public-ip>` จากเครื่องนอก
