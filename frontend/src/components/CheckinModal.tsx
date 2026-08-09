"use client";

import { usePathname } from "next/navigation";
import { useNotifyStore } from "@/lib/notify";
import { api } from "@/lib/api";
import { NeonButton } from "./NeonButton";

// ★ หน้าที่ห้ามเด้ง modal — จอทำงานของ staff/จอใหญ่
//   บนหน้า /scan modal จะบังเต็มจอจนสแกนคนถัดไปไม่ได้
//   (เกิดชัดตอน admin สแกนบัตรตัวเอง แต่คนละคนก็ไม่ควรเด้งอยู่ดี)
const SUPPRESS_ON = ["/scan", "/admin", "/display"];

// Modal คงอยู่ (ไม่ใช่ toast 3.5 วิ) — เด้งเวลาถูกเช็คอิน มีปุ่มไปกรอกฟอร์ม Attendance
export function CheckinModal() {
  const { open, payload, close } = useNotifyStore();
  const pathname = usePathname();

  if (SUPPRESS_ON.some((p) => pathname?.startsWith(p))) return null;
  if (!open || !payload) return null;

  const dismiss = () => {
    // best-effort suppress login re-show 1h (live push ยังทำงานได้)
    api.dismissATPrompt().catch(() => {});
    close();
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
      <div className="retro-panel scanlines neon-border-pink max-w-sm w-full p-6 space-y-4 text-center">
        <h2 className="font-mono text-2xl neon-text-pink tracking-widest">เช็คอินสำเร็จ</h2>
        <p className="text-neon-yellow font-mono text-lg">
          +{payload.coins_awarded} coin · วันที่ {payload.event_day}
        </p>
        <p className="text-white/70 text-sm">กรุณากรอกฟอร์ม Attendance</p>
        <div className="flex flex-col gap-2 pt-2">
          {payload.form_url && (
            <a href={payload.form_url} target="_blank" rel="noopener noreferrer">
              <NeonButton variant="pink" className="w-full">ไปกรอกฟอร์ม</NeonButton>
            </a>
          )}
          <NeonButton variant="ghost" className="w-full" onClick={dismiss}>ปิด</NeonButton>
        </div>
      </div>
    </div>
  );
}
