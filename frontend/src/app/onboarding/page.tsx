"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { NeonButton } from "@/components/NeonButton";
import { RetroCard } from "@/components/RetroCard";
import { toast } from "@/components/Toaster";
import { FACULTIES } from "@/lib/faculty";
import { ProtectedRoute } from "@/components/ProtectedRoute";

// ★ ต้องมี ProtectedRoute — ของเดิมไม่มี ทำให้คนที่ยังไม่ login เปิดหน้านี้ได้
//   กรอกจนครบแล้วกดบันทึกถึงจะโดนเด้งไป /login แล้วข้อมูลที่พิมพ์หายทั้งหมด
export default function OnboardingPage() {
  return (
    <ProtectedRoute>
      <OnboardingForm />
    </ProtectedRoute>
  );
}

function OnboardingForm() {
  const router = useRouter();
  const { user, setUser } = useAuth();
  const [displayName, setDisplayName] = useState(user?.display_name || "");
  const [faculty, setFaculty] = useState(user?.faculty || "");
  const [department, setDepartment] = useState(user?.department || "");
  const [studentId, setStudentId] = useState(user?.student_id || "");
  const [consentPhoto, setConsentPhoto] = useState(false);
  const [saving, setSaving] = useState(false);

  async function save() {
    // ★ ทุกคนกรอกครบเหมือนกันหมด ไม่แยกตาม domain ของอีเมล
    //   ที่เปิดรับอีเมลทุก domain ไม่ได้แปลว่าเปิดให้คนนอกมหาวิทยาลัยเข้างาน —
    //   แปลว่าคนที่หน้างานไม่ได้ล็อกอินเมลมหิดลไว้ในมือถือก็ใช้เมลอื่นเข้าได้
    //   ตัวตนจริงมาจากข้อมูลที่กรอก ไม่ใช่จาก domain ของอีเมล
    //   backend กันไว้อีกชั้น (PROFILE_INCOMPLETE) ตรงนี้แค่บอกก่อนกดส่ง
    const sid = studentId.trim();
    if (!displayName.trim()) return toast("ยังไม่ได้กรอกชื่อเล่น", "warn");
    if (!faculty) return toast("ยังไม่ได้เลือกคณะ", "warn");
    if (!department) return toast("ยังไม่ได้เลือกสาขาวิชา", "warn");
    if (!sid) return toast("ยังไม่ได้กรอกรหัสนักศึกษา", "warn");
    if (!/^\d{7}$/.test(sid)) return toast("รหัสนักศึกษาต้องเป็นตัวเลข 7 หลัก", "warn");
    if (!consentPhoto) return toast("ต้องยินยอมให้ใช้รูปก่อน", "warn");
    setSaving(true);
    try {
      const updated = await api.patchMe({
        display_name: displayName.trim(),
        faculty: faculty || undefined,
        department: department || undefined,
        student_id: sid || undefined,
        consent_photo: consentPhoto,
      });
      setUser(updated);
      toast("บันทึกเรียบร้อย", "success");
      router.replace("/");
    } catch (e: any) {
      toast(e.message || "บันทึกไม่สำเร็จ", "error");
    } finally {
      setSaving(false);
    }
  }

  const facultyObj = FACULTIES.find((f) => f.code === faculty);

  return (
    <div className="max-w-md mx-auto py-6 space-y-4">
      <div className="text-center mb-4">
        <h1 className="font-mono text-2xl neon-text-pink tracking-widest">ตั้งค่าโปรไฟล์</h1>
        <p className="text-white/50 text-sm mt-1">กรอกให้ครบแล้วเริ่มใช้งานได้เลย</p>
      </div>

      <RetroCard glow="purple">
        <Field label="ชื่อเล่น">
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            maxLength={40}
            className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white"
          />
        </Field>

        <Field label="คณะ">
          <select
            value={faculty}
            onChange={(e) => { setFaculty(e.target.value); setDepartment(""); }}
            className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white"
          >
            <option value="">— เลือกคณะ —</option>
            {FACULTIES.map((f) => (
              <option key={f.code + f.name} value={f.code}>
                {f.name} ({f.code})
              </option>
            ))}
          </select>
        </Field>

        <Field label="สาขาวิชา">
          <select
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
            disabled={!faculty}
            className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white disabled:opacity-40"
          >
            <option value="">— เลือกสาขา —</option>
            {facultyObj?.departments.map((d) => (
              <option key={d.code + d.name} value={d.code}>
                {d.name}
              </option>
            ))}
          </select>
          {faculty && department && (
            <p className="text-xs text-neon-yellow mt-1 font-mono">
              รหัสเก็บในระบบ: {faculty}
              {department}
            </p>
          )}
        </Field>

        <Field label="รหัสนักศึกษา">
          <input
            value={studentId}
            onChange={(e) => setStudentId(e.target.value.replace(/\D/g, ""))}
            inputMode="numeric"
            maxLength={7}
            className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white font-mono"
          />
          <p className="text-xs text-white/40 mt-1">
            7 หลัก — ใช้เช็คอินแทน QR ได้ตอนมือถือแบตหมด
          </p>
        </Field>

        {/* ★ ไม่มีช่อง Instagram ที่นี่โดยตั้งใจ
            ชื่อ IG ถูกถามตอนจะส่งรูปขึ้นจอ (หน้า /ig) เท่านั้น
            ถ้าเอามาบังคับกรอกตรงนี้ คนที่ไม่มี IG จะผ่านหน้านี้ไม่ได้
            = ไม่ได้บัตร = เช็คอินเข้างานไม่ได้เลย */}

        <label className="flex items-start gap-3 mt-4 cursor-pointer">
          <input
            type="checkbox"
            checked={consentPhoto}
            onChange={(e) => setConsentPhoto(e.target.checked)}
            className="mt-1 w-5 h-5 accent-[var(--neon-pink)]"
          />
          <span className="text-sm text-white/70">
            ยินยอมให้ใช้รูปและข้อมูลในการแสดงบนจอหน้างาน ตามนโยบาย PDPA
          </span>
        </label>

        <div className="mt-6">
          <NeonButton variant="pink" loading={saving} onClick={save} className="w-full">
            บันทึกและเริ่มใช้งาน
          </NeonButton>
        </div>
      </RetroCard>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <label className="block text-sm text-white/70 mb-1">{label}</label>
      {children}
    </div>
  );
}
