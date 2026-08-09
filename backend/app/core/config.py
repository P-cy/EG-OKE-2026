"""Application settings — โหลดจาก .env ผ่าน pydantic-settings"""
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    ENABLE_DOCS: bool = False
    FRONTEND_ORIGIN: str = "http://localhost:3000"
    API_BASE_URL: str = "http://localhost:8000"

    # Mongo
    MONGO_URI: str
    MONGO_DB: str = "egoke2026"
    MONGO_MAX_POOL: int = 100
    MONGO_MIN_POOL: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: str = ""

    # Auth
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_SECONDS: int = 900
    REFRESH_TOKEN_TTL_DAYS: int = 30
    TOKEN_VERSION: int = 1

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    # ★ ปล่อยว่าง = รับทุก domain — หน้างานคนไม่ได้ล็อกอินเมลมหิดลไว้ในมือถือ
    #   ใส่ค่าเมื่อไหร่ก็กลับไปจำกัดเฉพาะ domain นั้นทันที (ไม่ต้อง deploy)
    ALLOWED_EMAIL_DOMAINS: str = ""
    # ★ อีเมลที่เป็น admin — คั่นด้วยจุลภาค
    # ตอน login ถ้าอีเมลอยู่ในลิสต์นี้จะได้ role "admin" อัตโนมัติ (promote เท่านั้น ไม่ demote)
    ADMIN_EMAILS: str = ""

    # QR / check-in
    QR_SIGNING_KEY: str
    QR_VERSION: int = 1
    TOTP_KEY: str = ""
    TOTP_PERIOD: int = 30
    TOTP_WINDOW: int = 1
    STRICT_QR_MODE: bool = False
    CHECKIN_COINS: int = 10

    # ── โควตาการจ่ายเหรียญของ staff ──────────────────────────────────
    # staff_grant เป็นทางเดียวที่เหรียญเข้าระบบได้แบบไม่มีเพดานในตัว
    # (เช็คอินปิดด้วย dedupe รายวัน / กิจกรรมจำกัดครั้งต่อคน / วงล้อ EV ติดลบ + 3 ครั้ง)
    # ปรับได้ใน .env แล้ว restart api (~5 วิ) ถ้าหน้างานพบว่าตั้งไว้แคบ/หลวมไป
    STAFF_GRANT_MAX_PER_SCAN: int = 200        # ต่อการสแกน 1 ครั้ง — กันพิมพ์ผิดหลัก
    # ★ ด่านที่กัน "จ่ายให้เพื่อน" โดยตรง — staff คนหนึ่ง → คนหนึ่ง ต่อวัน
    STAFF_GRANT_PER_USER_DAILY: int = 300
    # ★ ด่านที่กัน "ไล่เก็บจาก staff หลายคน" — คนหนึ่งรับรวมจากทุกบูธ ต่อวัน
    USER_GRANT_RECEIVE_DAILY: int = 1500
    # เบรกเกอร์กันเครื่องหลุดมือ — ตั้งหลวมไว้ ไม่ให้ขวางบูธที่คนต่อคิวจริง
    STAFF_GRANT_DAILY_BUDGET: int = 20000

    # Wheel
    WHEEL_SERVER_SEED: str = ""

    # Attendance — ลิงก์ Google Form ที่จะเด้งให้คนเข้างานกรอกหลังเช็คอิน
    # (ว่าง = ปุ่ม "ไปกรอกฟอร์ม" ถูกซ่อน)
    ATTENDANCE_FORM_URL: str = ""

    # Privacy
    IP_PEPPER: str = "changeme"

    # Feature defaults
    REQUIRE_CHECKIN_TO_VOTE: bool = False
    IG_SUBMISSIONS_PER_DAY: int = 5
    # ★ ถอด IG_APPROVED_COINS ออกแล้ว — การขึ้นจอเป็นของที่ "ซื้อ" ด้วยเหรียญ
    #   ไม่ใช่รางวัล ของเดิมจ่ายคืน 50 ตอนอนุมัติ ทั้งที่หักไปแค่ 20 = ส่งรูปแล้วได้กำไร

    # Realtime
    SNAPSHOT_INTERVAL_MS: int = 1000
    WS_HEARTBEAT_SECONDS: int = 20
    WS_MAX_QUEUE: int = 50
    DISPLAY_TOKEN: str = ""

    # Ops
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: str = ""
    METRICS_ALLOWED_IPS: str = "127.0.0.1"

    # ── derived ────────────────────────────────────────────────────────
    @property
    def allowed_domains(self) -> set[str]:
        return {d.strip().lower() for d in self.ALLOWED_EMAIL_DOMAINS.split(",") if d.strip()}

    @property
    def admin_emails(self) -> set[str]:
        """อีเมลที่เป็น admin — lowercase, กัน typo พิมพ์ใหญ่เล็กไม่เท่ากัน"""
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    @property
    def frontend_origins(self) -> list[str]:
        """รองรับหลาย origin คั่นจุลภาค — ตอนทดสอบหน้างานต้องเปิดจากมือถือผ่าน LAN IP
        เช่น FRONTEND_ORIGIN=http://localhost:3000,http://192.168.1.20:3000
        (ถ้าไม่ใส่ origin ของมือถือ ทุก API call จะโดน CORS บล็อก)
        """
        return [o.strip().rstrip("/") for o in self.FRONTEND_ORIGIN.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.ENV == "production"

    @field_validator("JWT_SECRET", "QR_SIGNING_KEY")
    @classmethod
    def _no_placeholder_secrets(cls, v: str, info) -> str:
        if "CHANGE_ME" in v:
            # เตือนดังๆ ตอน dev, ตายเลยตอน prod (เช็คใน validate_production)
            print(f"⚠️  {info.field_name} ยังเป็นค่า placeholder — เปลี่ยนก่อน deploy!")
        if len(v) < 16:
            raise ValueError(f"{info.field_name} สั้นเกินไป (ต้อง >= 16 ตัวอักษร)")
        return v

    def validate_production(self) -> None:
        """เรียกตอน startup ถ้า ENV=production — fail fast ดีกว่าปล่อยให้รันแล้วโดนแฮก"""
        if not self.is_prod:
            return
        problems: list[str] = []
        for name in ("JWT_SECRET", "QR_SIGNING_KEY", "TOTP_KEY", "WHEEL_SERVER_SEED"):
            val = getattr(self, name, "")
            if not val or "CHANGE_ME" in val or len(val) < 32:
                problems.append(f"{name} ไม่ปลอดภัย (ต้องยาว >= 32 และไม่ใช่ค่า default)")
        if self.DEBUG:
            problems.append("DEBUG ต้องเป็น false ใน production")
        if self.ENABLE_DOCS:
            problems.append("ENABLE_DOCS ต้องเป็น false ใน production")
        if self.IP_PEPPER == "changeme":
            problems.append("IP_PEPPER ยังเป็นค่า default")
        if not self.GOOGLE_CLIENT_ID:
            problems.append("GOOGLE_CLIENT_ID ว่าง")
        if problems:
            raise RuntimeError(
                "การตั้งค่า production ไม่ปลอดภัย:\n  - " + "\n  - ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
