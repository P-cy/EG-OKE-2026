"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import Link from "next/link";
import { api } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { Spinner } from "@/components/Spinner";
import { toast } from "@/components/Toaster";

export default function TicketPage() {
  return (
    <ProtectedRoute>
      <TicketContent />
    </ProtectedRoute>
  );
}

function TicketContent() {
  const [wakeLock, setWakeLock] = useState(false);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["my-tickets"],
    queryFn: () => api.getMyTickets(),
    // ★ QR payload คงที่แล้ว (ผูกกับ issued_at) → poll แค่เพื่ออัปเดต "เข้าแล้ววันไหน"
    //   30 วิพอ, และหยุดตอนแท็บซ่อน — 5,000 คน poll ทุก 5 วิ = 1,000 req/s โดยเปล่าประโยชน์
    refetchInterval: () =>
      typeof document !== "undefined" && document.hidden ? false : 30_000,
  });

  // กันหน้าจอดับ เพื่อให้เจ้าหน้าที่สแกนติดง่าย
  useEffect(() => {
    let lock: any = null;
    (async () => {
      try {
        lock = await (navigator as any).wakeLock?.request("screen");
        setWakeLock(true);
      } catch {
        // อุปกรณ์ไม่รองรับก็ไม่เป็นไร
      }
    })();
    return () => { try { lock?.release(); } catch {} };
  }, []);

  const ticket = data?.[0];

  // cache payload ลง localStorage สำหรับตอนออฟไลน์
  useEffect(() => {
    if (ticket?.payload) {
      localStorage.setItem("qr:payload", ticket.payload);
      localStorage.setItem("qr:code", ticket.ticket_code);
    }
  }, [ticket]);

  const days = ticket?.checked_in_days ?? [];

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="font-mono text-2xl neon-text-pink tracking-widest">บัตรเข้างาน</h1>
        <p className="text-sm text-white/50 mt-1">QR ใบเดียว ใช้ได้ทั้งงาน</p>
      </div>

      <RetroCard glow="pink">
        {isLoading ? (
          <div className="flex justify-center py-10"><Spinner /></div>
        ) : ticket ? (
          <div className="text-center space-y-4">
            <div className="bg-white p-4 inline-block rounded neon-border-blue">
              <QRCodeSVG value={ticket.payload} size={240} level="M" includeMargin={false} />
            </div>

            {/* ★ QR ใบเดียวใช้ 2 งาน — ต้องบอกตรงใต้ QR ไม่ใช่ซ่อนในรายการช่วยเหลือด้านล่าง
                คนถามบ่อยว่า "อันนี้ของเช็คอินหรือของรับเหรียญ" แล้วไปหาบัตรใบที่สองที่ไม่มีอยู่จริง */}
            <div className="grid grid-cols-2 gap-2">
              <div className="border border-neon-green/40 bg-neon-green/5 px-3 py-2.5">
                <p className="font-mono text-sm text-neon-green">เช็คอินเข้างาน</p>
                <p className="text-[11px] text-white/45 mt-0.5 leading-snug">ที่ประตู ทุกวันที่มา</p>
              </div>
              <div className="border border-neon-yellow/40 bg-neon-yellow/5 px-3 py-2.5">
                <p className="font-mono text-sm text-neon-yellow">รับเหรียญที่บูธ</p>
                <p className="text-[11px] text-white/45 mt-0.5 leading-snug">เล่นกิจกรรมจบแล้วยื่นให้สแกน</p>
              </div>
            </div>

            <div>
              {/* ★ รหัสบัตรใหญ่ชัด — ถ้ากล้องเจ้าหน้าที่อ่านไม่ติด อ่านรหัสนี้ให้พิมพ์ได้เลย */}
              <p className="text-xs text-white/40 font-mono">รหัสบัตร (บอกเจ้าหน้าที่ได้ถ้าสแกนไม่ติด)</p>
              <button
                onClick={() => {
                  navigator.clipboard?.writeText(ticket.ticket_code)
                    .then(() => toast("คัดลอกรหัสบัตรแล้ว", "success"))
                    .catch(() => {});
                }}
                className="font-mono text-2xl neon-text-blue tracking-widest mt-1"
              >
                {ticket.ticket_code}
              </button>
              <p className="text-sm text-white/50 mt-2">สถานะ: {statusLabel(ticket.status)}</p>

              {/* รหัสหมุน — โชว์เฉพาะตอนระบบเปิดโหมดตรวจรหัสหมุนจริง */}
              {ticket.rotating_code && (
                <div className="mt-3">
                  <p className="text-xs text-white/40">รหัสหมุน (เปลี่ยนทุก 30 วิ)</p>
                  <p className="font-mono text-3xl neon-text-pink animate-flicker">{ticket.rotating_code}</p>
                  <p className="text-xs text-neon-yellow">เปลี่ยนใน {ticket.rotates_in ?? 30} วิ</p>
                </div>
              )}
            </div>

            {/* ★ เข้าแล้ววันไหนบ้าง */}
            <div>
              <p className="text-xs text-white/40 font-mono mb-2">สถานะเข้างาน</p>
              <div className="flex justify-center gap-2">
                {[1, 2, 3].map((d) => (
                  <span
                    key={d}
                    className={`px-3 py-1.5 font-mono text-sm border ${
                      days.includes(d)
                        ? "border-neon-green text-neon-green bg-neon-green/10"
                        : "border-white/20 text-white/30"
                    }`}
                  >
                    วันที่ {d} {days.includes(d) ? "✓" : ""}
                  </span>
                ))}
              </div>
            </div>

            <button onClick={() => refetch()} className="text-xs text-white/40 hover:text-white underline">
              รีเฟรช
            </button>
          </div>
        ) : (
          <div className="text-center text-white/50 py-8 space-y-3">
            <p>ยังไม่มีบัตร — กรุณาตั้งค่าโปรไฟล์ก่อน</p>
            <Link href="/onboarding" className="inline-block neon-border-pink px-4 py-2 text-neon-pink font-mono text-sm">
              ไปตั้งค่าโปรไฟล์
            </Link>
          </div>
        )}
      </RetroCard>

      <RetroCard glow="blue" title="QR นี้ใช้ทำอะไรได้บ้าง">
        <div className="space-y-2 text-sm text-white/60">
          <p>
            <span className="text-neon-green">เช็คอินเข้างาน</span> — ยื่นให้เจ้าหน้าที่สแกนที่ประตู
            ทุกวันที่มา (1 บัตรต่อคน ใช้ได้ทั้ง 3 วัน ไม่ต้องขอใบใหม่)
          </p>
          <p>
            <span className="text-neon-yellow">รับเหรียญที่บูธ</span> — เล่นกิจกรรมจบแล้วยื่นให้เจ้าหน้าที่บูธสแกน
            เหรียญเข้าทันที ดูว่ามีบูธอะไรบ้างที่หน้า{" "}
            <Link href="/quests" className="text-neon-pink underline">กิจกรรม</Link>
          </p>
          <div className="pt-2 mt-1 border-t border-white/10 space-y-2 text-white/50">
            <p>- ถ้าสแกนไม่ติด บอกรหัสบัตรหรือรหัสนักศึกษาให้เจ้าหน้าที่พิมพ์แทนได้</p>
            <p>- หน้านี้ทำงานได้แม้ออฟไลน์ (QR ถูกแคชไว้แล้ว)</p>
            {wakeLock && <p className="text-neon-green">เปิดกันหน้าจอดับแล้ว</p>}
          </div>
        </div>
      </RetroCard>
    </div>
  );
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    issued: "ใช้งานได้ปกติ",
    revoked: "ถูกยกเลิก",
    expired: "หมดอายุ",
  };
  return map[status] || status;
}
