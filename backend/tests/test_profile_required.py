"""ต้องกรอกอะไรบ้างก่อนเริ่มใช้งาน

★ ทุกคนกรอกครบเหมือนกันหมด ไม่แยกตาม domain ของอีเมล
  ที่เปิดรับอีเมลทุก domain ไม่ได้แปลว่าเปิดให้คนนอกมหาวิทยาลัยเข้างาน —
  แปลว่าคนที่หน้างานไม่ได้ล็อกอินเมลมหิดลไว้ในมือถือก็ใช้เมลอื่นเข้าได้
  ตัวตนจริงมาจากข้อมูลที่กรอก ไม่ใช่จาก domain ของอีเมล
"""
from app.services.profile import REQUIRED_FIELDS, missing_fields, needs_onboarding

COMPLETE = {
    "email": "someone@gmail.com",
    "display_name": "PP",
    "faculty": "EG",
    "department": "CO",
    "student_id": "6913099",
    "instagram_handle": "someone",
    "consent": {"tos": True},
}


def test_complete_profile_passes():
    assert missing_fields(COMPLETE) == []
    assert needs_onboarding(COMPLETE) is False


def test_every_required_field_blocks_on_its_own():
    """ขาดช่องไหนก็ต้องถูกส่งกลับไปกรอก — ไม่ใช่แค่บางช่อง"""
    for key, label in REQUIRED_FIELDS:
        doc = {**COMPLETE, key: ""}
        assert missing_fields(doc) == [label], f"ขาด {label} ต้องถูกจับได้"
        assert needs_onboarding(doc) is True


def test_missing_field_is_absent_not_just_empty():
    """ผู้ใช้เก่าที่ไม่มีคีย์นั้นใน document เลย ต้องถูกจับได้เหมือนกัน"""
    doc = {k: v for k, v in COMPLETE.items() if k != "student_id"}
    assert missing_fields(doc) == ["รหัสนักศึกษา"]


def test_missing_fields_lists_all_of_them():
    """บอกให้ครบทีเดียว ไม่ใช่ให้กรอกทีละช่องแล้วเด้ง error ทีละรอบ"""
    doc = {"email": "a@gmail.com", "consent": {"tos": True}}
    assert missing_fields(doc) == ["ชื่อเล่น", "คณะ", "สาขาวิชา", "รหัสนักศึกษา"]


def test_instagram_is_never_required():
    """★ คนที่ไม่มี IG ต้องผ่าน onboarding ได้

    เคยบังคับกรอก ผลคือคนไม่มี IG กรอกไม่ผ่าน → ไม่ได้บัตร → เช็คอินไม่ได้
    = ติดตายอยู่หน้าประตูตั้งแต่ยังไม่ทันเข้างาน
    ชื่อ IG ถูกถามตอนจะส่งรูปขึ้นจอ (หน้า /ig) ซึ่งคนกรอกเองอยู่แล้ว
    """
    assert "instagram_handle" not in [k for k, _label in REQUIRED_FIELDS]

    no_ig = {k: v for k, v in COMPLETE.items() if k != "instagram_handle"}
    assert missing_fields(no_ig) == []
    assert needs_onboarding(no_ig) is False

    # ใส่ค่าว่างมาก็ต้องผ่าน (คนกดข้ามช่องนั้นไป)
    assert needs_onboarding({**COMPLETE, "instagram_handle": ""}) is False


def test_domain_no_longer_changes_anything():
    """★ กันคนเผลอเอาเงื่อนไขแยกตาม domain กลับเข้ามา

    เคยมีตรรกะ "คนมหิดลบังคับกรอก คนนอกไม่ต้อง" ซึ่งเข้าใจโจทย์ผิด —
    งานนี้คนเข้างานเป็นนักศึกษาทั้งหมด ที่เปิดรับทุก domain เพราะหน้างาน
    เขาไม่ได้ล็อกอินเมลมหิดลไว้ ไม่ใช่เพราะจะให้คนนอกเข้า
    """
    for email in ("a@gmail.com", "b@student.mahidol.ac.th", "c@hotmail.com"):
        assert needs_onboarding({**COMPLETE, "email": email}) is False
        assert needs_onboarding({**COMPLETE, "email": email, "faculty": ""}) is True


def test_consent_is_still_the_first_gate():
    """ยังไม่ยอมรับเงื่อนไข = ต้องผ่าน onboarding อยู่ดี แม้กรอกครบแล้ว"""
    doc = {**COMPLETE, "consent": {}}
    assert needs_onboarding(doc) is True


def test_required_list_matches_the_form():
    """★ สัญญาระหว่าง backend กับหน้า /onboarding

    ถ้าเพิ่มช่องที่นี่แล้วลืมเพิ่มในฟอร์ม ผู้ใช้จะกรอกจนสุดแล้วโดน 400
    โดยไม่มีช่องให้กรอกสิ่งที่ขาด = เข้าเว็บไม่ได้เลย
    """
    assert [label for _k, label in REQUIRED_FIELDS] == [
        "ชื่อเล่น", "คณะ", "สาขาวิชา", "รหัสนักศึกษา",
    ]
