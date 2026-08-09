"use client";

import { useState } from "react";
import { downloadFile } from "@/lib/api";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { toast } from "@/components/Toaster";

// ดาวน์โหลดข้อมูลเป็น CSV — เปิดใน Excel / Google Sheets ได้ตรงๆ
// (ProtectedRoute roles=["admin"] ครอบมาจาก app/admin/layout.tsx แล้ว)
export default function AdminExportPage() {
  const [busy, setBusy] = useState<string | null>(null);
  const [day, setDay] = useState<number | undefined>(undefined);

  async function grab(key: string, path: string, name: string) {
    setBusy(key);
    try {
      await downloadFile(path, name);
      toast("ดาวน์โหลดแล้ว — ดูในโฟลเดอร์ Downloads", "success");
    } catch (e: any) {
      toast(e.message || "ดาวน์โหลดไม่สำเร็จ", "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <h1 className="font-mono text-2xl neon-text-pink tracking-widest text-center">ดาวน์โหลดข้อมูล</h1>

      <RetroCard glow="blue">
        <p className="text-sm text-white/60 leading-relaxed">
          ไฟล์เป็น CSV เปิดด้วย Excel หรือ Google Sheets ได้เลย
          เวลาในไฟล์แปลงเป็นเวลาไทยแล้ว (+7) ไม่ต้องบวกเอง
        </p>
      </RetroCard>

      {/* ── log การสแกน ── */}
      <RetroCard glow="pink" title="ประวัติการสแกนทั้งหมด">
        <p className="text-sm text-white/50 mb-3">
          หนึ่งแถวต่อการสแกนหนึ่งครั้ง — ใครเช็คอินตอนไหน กี่โมง ประตูไหน ใครเป็นคนสแกน
          รวมครั้งที่ถูกปฏิเสธด้วย (ใช้ตอนมีคนทักว่า &quot;ผมสแกนแล้ว&quot;)
        </p>

        <div className="flex flex-wrap gap-2 mb-3">
          {[undefined, 1, 2, 3].map((d) => (
            <button
              key={String(d)}
              onClick={() => setDay(d)}
              className={`px-3 py-1.5 font-mono text-xs ${day === d ? "neon-border-blue text-neon-blue" : "border border-white/20 text-white/40"}`}
            >
              {d === undefined ? "ทุกวัน" : `เฉพาะวัน ${d}`}
            </button>
          ))}
        </div>

        <NeonButton
          variant="pink"
          loading={busy === "checkins"}
          onClick={() =>
            grab(
              "checkins",
              `/admin/export/checkins.csv${day ? `?event_day=${day}` : ""}`,
              "egoke-checkins.csv",
            )
          }
        >
          ดาวน์โหลดประวัติการสแกน
        </NeonButton>
      </RetroCard>

      {/* ── รายชื่อ ── */}
      <RetroCard glow="blue" title="รายชื่อผู้เข้างาน">
        <p className="text-sm text-white/50 mb-3">
          หนึ่งแถวต่อหนึ่งคน — ชื่อเล่น ชื่อจริง อีเมล รหัสนักศึกษา คณะ สาขา
          และสรุปว่าเข้าวันไหนบ้าง เหรียญคงเหลือเท่าไหร่
        </p>
        <NeonButton
          variant="blue"
          loading={busy === "attendees"}
          onClick={() => grab("attendees", "/admin/export/attendees.csv", "egoke-attendees.csv")}
        >
          ดาวน์โหลดรายชื่อ
        </NeonButton>
      </RetroCard>

      {/* ── เหรียญ ── */}
      <RetroCard glow="purple" title="ประวัติเหรียญ">
        <p className="text-sm text-white/50 mb-3">
          ทุกการเคลื่อนไหวของเหรียญ เข้าและออก — ใครได้เท่าไหร่ จากอะไร ใครเป็นคนจ่าย
          จากเครื่องไหน พร้อมยอดคงเหลือหลังทุกรายการ
        </p>
        <div className="flex gap-2 flex-wrap">
          <NeonButton
            variant="purple"
            loading={busy === "coins"}
            onClick={() => grab("coins", "/admin/export/coins.csv", "egoke-coins.csv")}
          >
            ดาวน์โหลดทั้งหมด
          </NeonButton>
          {/* ทางลัดที่ใช้บ่อยที่สุด — กระทบยอดกับบูธตอนปิดงาน */}
          <NeonButton
            variant="ghost"
            loading={busy === "grants"}
            onClick={() =>
              grab("grants", "/admin/export/coins.csv?reason=staff_grant", "egoke-staff-grants.csv")
            }
          >
            เฉพาะที่ staff จ่ายที่บูธ
          </NeonButton>
        </div>
      </RetroCard>

      <RetroCard glow="purple" title="ข้อควรรู้">
        <ul className="text-xs text-white/45 space-y-1.5 list-disc list-inside leading-relaxed">
          <li>ไฟล์มีข้อมูลส่วนบุคคล (อีเมล ชื่อจริง รหัสนักศึกษา) — เก็บให้ดี อย่าส่งต่อในกลุ่มแชท</li>
          <li>ทุกครั้งที่กดดาวน์โหลดจะเป็นข้อมูล ณ วินาทีนั้น ไม่ใช่ไฟล์ที่อัปเดตเอง</li>
          <li>ถ้ามีคนเข้างานเยอะ ไฟล์ประวัติการสแกนอาจใช้เวลาโหลดสักครู่ ปล่อยให้เสร็จอย่าปิดหน้า</li>
        </ul>
      </RetroCard>
    </div>
  );
}
