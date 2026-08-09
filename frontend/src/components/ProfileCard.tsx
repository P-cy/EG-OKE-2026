"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { toast } from "@/components/Toaster";
import { facultyDisplay, FACULTIES } from "@/lib/faculty";
import { formatCoins } from "@/lib/format";

// ขนาดรูปโปรไฟล์ — สั้น โหลดเร็ว เพียงพอสำหรับวงกลมเล็ก
const AVATAR_SIZE = 256;
const AVATAR_MAX_SRC_MB = 8;

export function ProfileCard() {
  const { user, setUser } = useAuth();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(user?.display_name || "");
  const [fac, setFac] = useState(user?.faculty || "");
  const [dep, setDep] = useState(user?.department || "");
  const [sid, setSid] = useState(user?.student_id || "");
  const [saving, setSaving] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [exporting, setExporting] = useState(false);

  if (!user) return null;

  function pickAvatar() {
    fileRef.current?.click();
  }

  async function onPickAvatar(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      toast("ต้องเป็นไฟล์รูปเท่านั้น", "warn");
      return;
    }
    if (f.size > AVATAR_MAX_SRC_MB * 1024 * 1024) {
      toast(`รูปต้องไม่เกิน ${AVATAR_MAX_SRC_MB}MB`, "warn");
      return;
    }
    setAvatarUploading(true);
    try {
      const base64 = await resizeToSquare(f, AVATAR_SIZE);
      const updated = await api.uploadAvatar(base64, "image/jpeg");
      setUser(updated);
      qc.invalidateQueries({ queryKey: ["snapshot"] });
      toast("เปลี่ยนรูปโปรไฟล์แล้ว", "success");
    } catch (e: any) {
      toast(e.message || "อัปโหลดรูปไม่สำเร็จ", "error");
    } finally {
      setAvatarUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function save() {
    setSaving(true);
    try {
      const u = await api.patchMe({
        display_name: name.trim(),
        faculty: fac, department: dep,
        student_id: sid.trim() || undefined,
      });
      setUser(u);
      toast("บันทึกแล้ว", "success");
      setEditing(false);
    } catch (e: any) {
      toast(e.message || "บันทึกไม่สำเร็จ", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-md mx-auto space-y-4">
      <RetroCard glow="pink">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={pickAvatar}
            disabled={avatarUploading}
            title="คลิกเพื่อเปลี่ยนรูปโปรไฟล์"
            className="relative shrink-0 group disabled:opacity-60"
          >
            {user.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={user.avatar_url}
                alt={user.display_name}
                className="w-20 h-20 rounded-full neon-border-pink object-cover"
              />
            ) : (
              <span className="w-20 h-20 rounded-full neon-border-pink bg-bg-deep flex items-center justify-center text-2xl font-mono neon-text-pink">
                {user.display_name?.[0]?.toUpperCase() || "?"}
              </span>
            )}
            <span className="absolute inset-0 rounded-full flex items-center justify-center bg-black/60 text-white/80 text-xs font-mono opacity-0 group-hover:opacity-100 transition pointer-events-none">
              {avatarUploading ? "กำลังอัป..." : "เปลี่ยนรูป"}
            </span>
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            onChange={onPickAvatar}
            className="hidden"
          />
          <div className="flex-1">
            <h2 className="font-mono text-2xl neon-text-pink">{user.display_name}</h2>
            <p className="text-white/50 text-sm">{user.email}</p>
            <p className="text-neon-yellow font-mono mt-1">{formatCoins(user.coins_balance)} coin</p>
            {user.rank && <p className="text-white/40 text-xs">อันดับที่ {user.rank}</p>}
          </div>
        </div>
      </RetroCard>

      <RetroCard glow="blue" title="คณะและสาขา">
        {editing ? (
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-white/50 mb-1">คณะ</label>
              <select value={fac} onChange={(e) => { setFac(e.target.value); setDep(""); }} className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white">
                <option value="">เลือกคณะ</option>
                {FACULTIES.map((f) => <option key={f.code + f.name} value={f.code}>{f.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-white/50 mb-1">สาขาวิชา</label>
              <select value={dep} onChange={(e) => setDep(e.target.value)} disabled={!fac} className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white disabled:opacity-40">
                <option value="">เลือกสาขา</option>
                {FACULTIES.find((f) => f.code === fac)?.departments.map((d) => (
                  <option key={d.code + d.name} value={d.code}>{d.name}</option>
                ))}
              </select>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {(() => {
              const fd = facultyDisplay(user.faculty, user.department);
              return (
                <>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-white/90">{fd.facultyThai}</span>
                    <span className="font-mono text-xs text-neon-yellow shrink-0">{fd.facultyCode}</span>
                  </div>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-white/90">{fd.deptThaiShort}</span>
                    <span className="font-mono text-xs text-neon-yellow shrink-0">{fd.deptAbbr}</span>
                  </div>
                  {fd.deptEn && (
                    <p className="text-xs text-white/40 font-mono pt-1 border-t border-white/10">
                      {fd.facultyEn}<span className="text-white/20"> · </span>{fd.deptEn}
                    </p>
                  )}
                </>
              );
            })()}
          </div>
        )}
      </RetroCard>

      <RetroCard glow="purple" title="ข้อมูลทั่วไป">
        {editing ? (
          // ★ ชื่อช่องเป็น label จริง ไม่ใช่ placeholder
          //   ของเดิมใช้ placeholder เป็นชื่อช่อง พอพิมพ์ลงไปชื่อก็หายไปด้วย
          //   เหลือกล่องสามอันหน้าตาเหมือนกัน ไม่รู้ว่าอันไหนคืออะไร
          <div className="space-y-3">
            <label className="block">
              <span className="text-xs text-white/50 block mb-1">ชื่อเล่น</span>
              <input value={name} onChange={(e) => setName(e.target.value)} className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white" />
            </label>
            {/* ★ ไม่มีช่อง Instagram — ชื่อ IG ถามตอนจะส่งรูปขึ้นจอเท่านั้น (หน้า /ig) */}
            <label className="block">
              <span className="text-xs text-white/50 block mb-1">รหัสนักศึกษา (7 หลัก)</span>
              <input value={sid} onChange={(e) => setSid(e.target.value.replace(/\D/g, ""))} inputMode="numeric" maxLength={7} className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white font-mono" />
            </label>
          </div>
        ) : (
          <div className="space-y-1 text-sm">
            <p><span className="text-white/50">ชื่อเล่น:</span> {user.display_name}</p>
            <p><span className="text-white/50">รหัสนักศึกษา:</span> <span className="font-mono">{user.student_id || "-"}</span></p>
            <p><span className="text-white/50">บทบาท:</span> {user.roles.join(", ")}</p>
          </div>
        )}
      </RetroCard>

      {editing ? (
        <div className="flex gap-3">
          <NeonButton variant="pink" loading={saving} onClick={save}>บันทึก</NeonButton>
          <NeonButton variant="ghost" onClick={() => setEditing(false)}>ยกเลิก</NeonButton>
        </div>
      ) : (
        <NeonButton variant="blue" onClick={() => setEditing(true)}>แก้ไขโปรไฟล์</NeonButton>
      )}

      <RetroCard glow="blue" title="ข้อมูลของคุณ">
        <p className="text-sm text-white/60 mb-3">
          ดาวน์โหลดสำเนาข้อมูลทั้งหมดที่ระบบเก็บไว้เกี่ยวกับคุณ — โปรไฟล์
          ประวัติเหรียญทุกรายการ และประวัติการโหวต ได้เป็นไฟล์ JSON
        </p>
        <NeonButton variant="ghost" loading={exporting} onClick={exportData}>
          ดาวน์โหลดข้อมูลของฉัน
        </NeonButton>
        <p className="text-[11px] text-white/30 mt-3 leading-relaxed">
          เป็นสิทธิของคุณตาม พ.ร.บ. คุ้มครองข้อมูลส่วนบุคคล (PDPA)
          ไฟล์นี้มีข้อมูลส่วนตัว เก็บไว้กับตัวเอง อย่าส่งต่อให้คนอื่น
        </p>
      </RetroCard>
    </div>
  );

  async function exportData() {
    setExporting(true);
    try {
      await api.exportMyData();
      toast("ดาวน์โหลดแล้ว — ดูในโฟลเดอร์ดาวน์โหลดของเครื่อง", "success");
    } catch (e: any) {
      toast(e.message || "ดาวน์โหลดไม่สำเร็จ", "error");
    } finally {
      setExporting(false);
    }
  }
}

// อ่านรูป → วาดลง canvas แบบ cover-crop สี่เหลี่ยมจัตุรัส → JPEG base64 (ตัด data: prefix ออก)
// ทำฝั่ง browser เพื่อลดขนาดก่อนส่ง ไม่ให้ backend รับรูปใหญ่ดิบๆ
function resizeToSquare(file: File, size: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("อ่านไฟล์ไม่ได้"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("รูปไม่ถูกต้อง"));
      img.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext("2d");
        if (!ctx) return reject(new Error("ไม่รองรับ canvas"));
        // cover-crop: ใช้ส่วนกลางของรูป ไม่บิดให้เพี้ยน
        const src = Math.min(img.width, img.height);
        const sx = (img.width - src) / 2;
        const sy = (img.height - src) / 2;
        ctx.drawImage(img, sx, sy, src, src, 0, 0, size, size);
        const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
        resolve(dataUrl.split(",")[1] || "");
      };
      img.src = reader.result as string;
    };
    reader.readAsDataURL(file);
  });
}
