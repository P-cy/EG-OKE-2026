"use client";

import Link from "next/link";
import { RetroCard } from "@/components/RetroCard";
import { CheckinStatsCard } from "@/components/CheckinStatsCard";
import { useAuth } from "@/lib/auth";

// หน้าหลัก staff — ทางเข้า 3 ทางเป็นปุ่มใหญ่
// ★ ออกแบบให้กดถูกด้วยนิ้วโป้งข้างเดียว ยืนอยู่หน้างานถือมือถือ ไม่ได้นั่งหน้าคอม
export default function StaffHomePage() {
  const user = useAuth((s) => s.user);

  return (
    <div className="space-y-5">
      <div className="text-center">
        <h1 className="font-mono text-2xl text-neon-green tracking-widest">โหมดเจ้าหน้าที่</h1>
        <p className="text-white/40 text-sm mt-1">สวัสดี {user?.display_name || ""}</p>
      </div>

      <CheckinStatsCard />

      <Tile
        href="/scan"
        title="สแกนเช็คอินเข้างาน"
        sub="ที่ประตู — เลือกวันให้ตรงก่อนเริ่มสแกน"
        tone="green"
      />
      <Tile
        href="/scan"
        title="สแกนจ่ายเหรียญที่บูธ"
        sub={'เปิดหน้าสแกนแล้วกดแท็บ "จ่ายเหรียญ" — เลือก 20 / 50 / 100 หรือพิมพ์เอง แล้วสแกน'}
        tone="pink"
      />
      <Tile
        href="/staff/attendees"
        title="ค้นรายชื่อ (ไม่ใช้กล้อง)"
        sub="ใช้ตอนบัตร QR พัง / มือถือแบตหมด / สแกนไม่ติด"
        tone="blue"
      />

      <RetroCard glow="blue" title="วิธีใช้แบบสั้น">
        <ol className="text-sm text-white/60 space-y-1.5 list-decimal list-inside">
          <li>เปิดหน้าสแกน กดปุ่ม &quot;เปิดกล้อง&quot; ครั้งเดียวต่อการเปิดหน้า</li>
          <li>เลือกโหมดให้ตรง — เช็คอินเข้างาน หรือ จ่ายเหรียญ</li>
          <li>โหมดเช็คอินเลือกวันให้ตรง / โหมดจ่ายเหรียญเลือกจำนวนก่อน (ระบบจำค่าไว้ให้)</li>
          <li>ให้ผู้เข้างานเปิดหน้าบัตรของเขา แล้วส่องกล้องที่ QR</li>
          <li>จอเขียว = ผ่าน · เหลือง = เคยทำไปแล้ว · แดง = ไม่สำเร็จ อ่านข้อความใต้ตัวใหญ่</li>
          <li>สแกนคนเดิมซ้ำภายใน 20 วิ ระบบไม่จ่ายซ้ำ — ถ้าต้องจ่ายอีกจริง รอครบแล้วสแกนใหม่</li>
        </ol>
      </RetroCard>

      <RetroCard glow="purple" title="สิ่งที่ทำไม่ได้ในโหมดนี้">
        <p className="text-sm text-white/50">
          ยกเลิกเช็คอิน · ปรับเหรียญ · เปิด-ปิดกิจกรรม · อนุมัติ IG — ต้องให้ admin ทำให้
        </p>
      </RetroCard>
    </div>
  );
}

function Tile({ href, title, sub, tone }: {
  href: string; title: string; sub: string; tone: "green" | "pink" | "blue";
}) {
  const border = tone === "green" ? "border-neon-green/50 hover:bg-neon-green/10"
    : tone === "pink" ? "border-neon-pink/50 hover:bg-neon-pink/10"
    : "border-neon-blue/50 hover:bg-neon-blue/10";
  const text = tone === "green" ? "text-neon-green"
    : tone === "pink" ? "text-neon-pink" : "text-neon-blue";

  return (
    <Link href={href} className="block">
      <div className={`border-2 ${border} px-5 py-5 transition-colors`}>
        <p className={`font-mono text-xl ${text}`}>{title}</p>
        <p className="text-sm text-white/50 mt-1">{sub}</p>
      </div>
    </Link>
  );
}
