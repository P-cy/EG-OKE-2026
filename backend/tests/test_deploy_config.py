"""ตรวจว่า config ของ production ยังปลอดภัยอยู่

★ ทำไมต้องมีเทสต์ชุดนี้
  ทุกข้อในนี้เคยผิดจริงตอนตรวจก่อนขึ้น server และทุกข้อ "พังแบบเงียบ" —
  ระบบยังทำงานได้ปกติ ไม่มี error ไม่มี log ให้เห็น มีแค่ช่องโหว่เปิดทิ้งไว้:

    - mongo เปิด port 27017 ออก 0.0.0.0 โดยไม่มีรหัสผ่าน
    - redis เปิด port 6379 ออก 0.0.0.0 โดยไม่มีรหัสผ่าน
    - nginx กลืน security header ทิ้งใน location ที่มี add_header ของตัวเอง
    - .gitignore ไม่ครอบ .env ที่มี GOOGLE_CLIENT_SECRET

  เทสต์เป็นทางเดียวที่จะรู้ว่ามันกลับมาผิดอีก — เพราะดูจากหน้าเว็บไม่ออก

หมายเหตุ: รากของ repo ถูก mount เข้ามาที่ /repo (ดู volumes ใน docker-compose.yml)
ถ้ารัน pytest นอก container จะอ่านจาก path จริงในโปรเจกต์แทน
"""
from pathlib import Path

import pytest
import yaml

# ใน container ราก repo อยู่ที่ /repo — นอก container ไต่ขึ้นไปจากไฟล์นี้
_CANDIDATES = (Path("/repo"), Path(__file__).resolve().parents[2])
ROOT = next((p for p in _CANDIDATES if (p / "backend" / "docker-compose.prod.yml").exists()), None)

pytestmark = pytest.mark.skipif(
    ROOT is None, reason="ไม่ได้ mount ราก repo (ดู volumes ใน docker-compose.yml)"
)

BACKEND = ROOT / "backend" if ROOT else None


def _compose() -> dict:
    return yaml.safe_load((BACKEND / "docker-compose.prod.yml").read_text())


def _nginx_template() -> str:
    return (BACKEND / "nginx" / "nginx.conf.template").read_text()


def _env_example() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (BACKEND / ".env.production.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ── port ที่เปิดออกนอกเครื่อง ────────────────────────────────────────────

def test_only_nginx_publishes_ports():
    """★ ข้อสำคัญที่สุดในไฟล์นี้

    บนเครื่องตัวเองการเปิด port 27017 ไม่เป็นไร แต่บน VPS ที่มี public IP
    มันคือฐานข้อมูลที่ใครก็ต่อได้ (มี bot กวาด IPv4 ทั้งช่วงหา mongo/redis
    ที่เปิดทิ้งไว้ตลอดเวลา — เจอภายในไม่กี่ชั่วโมง)
    """
    services = _compose()["services"]
    publishing = {name: svc["ports"] for name, svc in services.items() if svc.get("ports")}
    assert set(publishing) == {"nginx"}, (
        f"มี service ที่เปิด port ออกนอกเครื่องนอกจาก nginx: {sorted(set(publishing) - {'nginx'})}"
    )


def test_nginx_publishes_only_http_and_https():
    ports = _compose()["services"]["nginx"]["ports"]
    host_ports = {str(p).split(":")[0].strip('"') for p in ports}
    assert host_ports == {"80", "443"}, f"nginx เปิด port แปลกๆ: {host_ports}"


@pytest.mark.parametrize("service", ["mongo", "redis", "api", "ws", "worker", "broadcaster"])
def test_backend_services_have_no_published_ports(service):
    assert "ports" not in _compose()["services"][service], (
        f"{service} ไม่ควรเปิด port ออกนอกเครื่อง — คุยกันในเครือข่าย docker พอ"
    )


# ── รหัสผ่านฐานข้อมูล ────────────────────────────────────────────────────

def test_mongo_requires_authentication():
    """--keyFile เปิด internal auth ของ replica set และเปิด --auth ให้ด้วย

    replica set + access control ต้องมาคู่กัน ใส่แค่ --auth เฉยๆ mongod ไม่ยอมบูต
    """
    cmd = _compose()["services"]["mongo"]["command"]
    assert "--keyFile" in cmd, "mongo ต้องเปิด access control ด้วย --keyFile"
    assert "--replSet" in cmd


def test_mongo_uri_carries_credentials():
    env = _compose()["x-app-env"]
    uri = env["MONGO_URI"]
    assert "${MONGO_ROOT_USER}" in uri and "${MONGO_ROOT_PASSWORD}" in uri, (
        "MONGO_URI ต้องมี user/password — เวอร์ชันก่อนหน้าเป็น mongodb://mongo:27017/... เปล่าๆ"
    )
    assert "authSource=admin" in uri, "ไม่มี authSource=admin จะ login ไม่ผ่าน"


def test_redis_requires_password():
    cmd = _compose()["services"]["redis"]["command"]
    assert "--requirepass" in cmd
    assert "${REDIS_PASSWORD}" in cmd
    assert "${REDIS_PASSWORD}" in _compose()["x-app-env"]["REDIS_URL"]


def test_redis_never_evicts_keys():
    """redis ที่นี่ถือคะแนนโหวตจริง ไม่ใช่ cache ที่ทิ้งได้

    ถ้าเป็น allkeys-lru พอแรมใกล้เต็มมันจะลบ key ทิ้งเงียบๆ = คะแนนโหวตหาย
    โดยไม่มีอะไรฟ้อง noeviction แปลว่า "เต็มแล้วปฏิเสธการเขียน" ซึ่งดังพอให้รู้ตัว
    """
    assert "--maxmemory-policy noeviction" in _compose()["services"]["redis"]["command"]


# ── ค่า production ที่ห้ามหลุด ──────────────────────────────────────────

def test_production_env_example_is_hardened():
    env = _env_example()
    assert env["ENV"] == "production"
    assert env["DEBUG"] == "false"
    assert env["ENABLE_DOCS"] == "false", "ENABLE_DOCS=true = เปิดโครงสร้าง API ให้คนนอกอ่าน"


def test_production_env_example_has_no_real_secrets():
    """ไฟล์ตัวอย่างต้องขึ้น git ได้ — ค่า secret ทุกตัวต้องว่าง"""
    env = _env_example()
    for key in ("JWT_SECRET", "QR_SIGNING_KEY", "TOTP_KEY", "WHEEL_SERVER_SEED",
                "IP_PEPPER", "DISPLAY_TOKEN", "MONGO_ROOT_PASSWORD", "REDIS_PASSWORD",
                "GOOGLE_CLIENT_SECRET"):
        assert env[key] == "", f"{key} มีค่าอยู่ในไฟล์ตัวอย่าง — ห้ามขึ้น git"


def test_env_example_has_no_inline_comments_after_values():
    """★ เคยพังจริงเพราะข้อนี้

    เดิมไฟล์ตัวอย่างเขียนแบบ  JWT_SECRET=        # deploy-init.sh สร้างให้
    ทำให้ deploy-init.sh มองว่า "ช่องนี้มีค่าแล้ว" เลยไม่สร้าง secret ให้สักตัว
    แล้วจบด้วยข้อความว่าสำเร็จ — พังแบบเงียบสนิท
    นอกจากนี้ตัวอ่าน .env แต่ละตัวยังตัด comment ไม่เหมือนกัน บางตัวเอา
    "# อธิบาย" ไปเป็นส่วนหนึ่งของรหัสผ่านด้วย
    """
    bad = [
        line for line in (BACKEND / ".env.production.example").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" in line and "#" in line
    ]
    assert bad == [], f"มี comment ต่อท้ายค่า: {bad}"


# ── nginx ────────────────────────────────────────────────────────────────

def test_sse_location_disables_buffering():
    """★ ถ้า nginx บัฟเฟอร์ SSE โมดัล "เช็คอินสำเร็จ" จะไม่เด้งบนมือถือคนเข้างาน

    proxy_buffering เปิดเป็นค่า default — nginx จะกอง chunk รอจนเต็ม buffer
    ก่อนค่อยส่งต่อ ซึ่งกับ stream ที่ไม่มีวันจบก็คือไม่ส่งเลย
    """
    tpl = _nginx_template()
    start = tpl.index("location = /v1/me/stream")
    block = tpl[start:tpl.index("}", start)]
    assert "proxy_buffering off" in block
    # default 30s ใน proxy_common.conf จะตัด SSE ทิ้งทุกครึ่งนาที = reconnect ทั้งงาน
    assert "proxy_read_timeout 3600s" in block


def test_every_location_with_add_header_reincludes_security_headers():
    """★ กฎ add_header ของ nginx: scope ล่างที่มี add_header ของตัวเอง
    จะ "ทิ้ง" add_header ที่สืบทอดมาทั้งหมด ไม่ใช่รวมกัน

    เจอตอนเทียบ header จริง — /healthz ส่งครบ 4 ตัว แต่ /v1/live/snapshot ส่ง 0
    เพราะมันมี add_header X-Cache-Status ของตัวเอง
    nginx -t ผ่าน เว็บใช้ได้ปกติ ไม่มีอะไรบอกว่า HSTS หายไป
    """
    tpl = _nginx_template()
    offenders = []
    for chunk in tpl.split("location ")[1:]:
        block = chunk[: chunk.index("\n    }")] if "\n    }" in chunk else chunk
        name = block.split("{")[0].strip()
        if "add_header" in block and "security_headers.conf" not in block:
            offenders.append(name)
    assert offenders == [], (
        f"location เหล่านี้มี add_header เอง แต่ไม่ได้ include security_headers.conf "
        f"→ HSTS/nosniff/X-Frame-Options จะหายไปเงียบๆ: {offenders}"
    )


def test_nginx_has_no_per_ip_rate_limit():
    """★ ตั้งใจไม่มี — ไม่ใช่ลืม

    ผู้เข้างาน ~5,000 คนต่อ wifi มหาวิทยาลัยเส้นเดียวกัน = ออกเน็ตด้วย public IP
    ไม่กี่ตัว (NAT) ในสายตา nginx คือ "คนเดียว" → limit ต่อ IP จะเหมารวมคนทั้งงาน
    การกันยิงรัวของจริงอยู่ที่ app/core/ratelimit.py ซึ่งนับต่อผู้ใช้
    """
    tpl = _nginx_template()
    active = [
        line for line in tpl.splitlines()
        if not line.strip().startswith("#")
        and ("limit_req " in line or "limit_conn " in line)
    ]
    assert active == [], f"มี rate limit ต่อ IP ที่จะพังเพราะ NAT ของมหาวิทยาลัย: {active}"


def test_camera_permission_policy_is_on_the_web_domain():
    """Permissions-Policy ต้องอยู่บน server block ของหน้าเว็บ ไม่ใช่ของ API

    กล้องถูกเรียกจากหน้า /scan ซึ่งเสิร์ฟจากโดเมนหน้าเว็บ ใส่ผิดที่ =
    staff กดเปิดกล้องแล้วเบราว์เซอร์ปฏิเสธโดยไม่บอกเหตุผล
    """
    tpl = _nginx_template()
    app_block = tpl[tpl.index("server_name ${APP_DOMAIN}"):]
    assert "camera=(self)" in app_block


# ── git ──────────────────────────────────────────────────────────────────

def test_gitignore_covers_secrets():
    """★ ก่อนหน้านี้ทั้งโปรเจกต์ไม่มี .gitignore ที่ root เลย

    backend/.env (มี GOOGLE_CLIENT_SECRET, JWT_SECRET, QR_SIGNING_KEY,
    DISPLAY_TOKEN) จะติดขึ้น GitHub ทันทีที่ `git add backend/`
    """
    ignore = (ROOT / ".gitignore").read_text()
    for pattern in (".env", ".env.*", "secrets/", "*.pem", "*.key"):
        assert pattern in ignore, f".gitignore ไม่มี {pattern}"
    # ต้องยกเว้นไฟล์ตัวอย่างไว้ ไม่งั้นคนโคลนมาไม่มี template ให้เริ่ม
    assert "!.env.example" in ignore
    assert "!.env.production.example" in ignore
