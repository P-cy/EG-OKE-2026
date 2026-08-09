"""ใครเข้าใช้งานได้บ้าง

หน้างานคนส่วนใหญ่ไม่ได้ล็อกอินเมลมหิดลไว้ในมือถือ ถ้าบังคับต้องมหิดล
จะกลายเป็นคอขวดที่ประตู — คนต้องยืนล็อกอินใหม่ทั้งแถว
ตอนนี้ ALLOWED_EMAIL_DOMAINS ปล่อยว่าง = รับทุก domain
แต่ต้องกลับไปจำกัดได้ทันทีด้วยการใส่ค่าใน .env โดยไม่ต้อง deploy
"""
import pytest

from app.core.config import settings


@pytest.fixture
def restore_domains():
    original = settings.ALLOWED_EMAIL_DOMAINS
    yield
    settings.ALLOWED_EMAIL_DOMAINS = original


def _domain_allowed(email: str) -> bool:
    """ตรรกะเดียวกับชั้นที่ 5 ใน verify_google_token"""
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    allowed = settings.allowed_domains
    return not allowed or domain in allowed


def test_empty_allowlist_accepts_every_domain(restore_domains):
    settings.ALLOWED_EMAIL_DOMAINS = ""
    assert settings.allowed_domains == set()
    for email in (
        "someone@gmail.com",
        "a@student.mahidol.ac.th",
        "b@hotmail.co.th",
        "c@outlook.com",
    ):
        assert _domain_allowed(email), f"{email} ต้องเข้าได้"


def test_setting_a_value_restores_the_restriction(restore_domains):
    """ปุ่มฉุกเฉิน: ถ้าเจอคนนอกสแปม ใส่ค่าใน .env แล้ว restart ก็ปิดได้เลย"""
    settings.ALLOWED_EMAIL_DOMAINS = "student.mahidol.ac.th,mahidol.ac.th"
    assert _domain_allowed("a@student.mahidol.ac.th")
    assert _domain_allowed("b@mahidol.ac.th")
    assert not _domain_allowed("c@gmail.com")


def test_allowlist_is_trimmed_and_case_insensitive(restore_domains):
    settings.ALLOWED_EMAIL_DOMAINS = " Mahidol.AC.TH , gmail.com "
    assert settings.allowed_domains == {"mahidol.ac.th", "gmail.com"}
    assert _domain_allowed("x@MAHIDOL.AC.TH")


def test_default_config_is_open_to_everyone():
    """กันคนเผลอ commit ค่าที่ล็อกไว้เฉพาะมหิดลกลับเข้ามา"""
    from app.core.config import Settings

    assert Settings.model_fields["ALLOWED_EMAIL_DOMAINS"].default == "", (
        "ค่า default ต้องเป็นค่าว่าง (รับทุก domain) — "
        "ถ้าจะจำกัดให้ตั้งใน .env ไม่ใช่ hardcode ในโค้ด"
    )
