"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { ProtectedRoute } from "@/components/ProtectedRoute";

// ★ หน้า admin แยกออกจากหน้าผู้ใช้ทั้งหมด
//   ของเดิมยัด nav ของ admin ต่อท้าย nav ผู้ใช้ในแถบเดียวกัน
//   บนมือถือมันกลายเป็นแถบยาวเลื่อนไม่จบ 15 ปุ่ม และ staff กดผิดหน้าประจำ
//   ตอนนี้เป็นคนละโหมด: สีต่างกัน nav คนละชุด มีปุ่มสลับกลับไปมา
//
// ★ /scan ต้องอยู่ใน nav นี้ — ของเดิมตกหล่นไป
//   หน้าสแกน (กล้อง) อยู่นอก /admin/* เพราะเป็นจอเต็ม ไม่มีแถบ nav
//   พอ nav ไม่มีลิงก์ไปหา มันกลายเป็นหน้าที่เข้าไม่ถึงเลย ต้องพิมพ์ URL เอง
//   คนกด "เช็คชื่อ" ก็ไปเจอหน้าค้นรายชื่อด้วยมือ แล้วนึกว่ากล้องหาย
const adminNav = [
  { href: "/admin", label: "แดชบอร์ด" },
  { href: "/scan", label: "สแกน QR", external: true },
  { href: "/admin/attendees", label: "เช็คชื่อด้วยมือ" },
  { href: "/admin/quests", label: "กิจกรรม" },
  { href: "/admin/rounds", label: "รอบโหวต" },
  { href: "/admin/ig", label: "คิว IG" },
  { href: "/admin/users", label: "ผู้ใช้" },
  { href: "/admin/grants", label: "เหรียญที่จ่าย" },
  { href: "/admin/export", label: "ดาวน์โหลด" },
  { href: "/admin/audit", label: "ประวัติ" },
  { href: "/admin/config", label: "ฉุกเฉิน" },
];

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute roles={["admin"]}>
      <AdminChrome>{children}</AdminChrome>
    </ProtectedRoute>
  );
}

function AdminChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user } = useAuth();

  return (
    <div className="min-h-screen flex flex-col">
      {/* แถบบน — สีชมพูล้วน ต่างจากฝั่งผู้ใช้ที่เป็นน้ำเงิน กันสับสนว่าอยู่โหมดไหน */}
      <header className="retro-panel border-b-2 border-neon-pink/50 backdrop-blur sticky top-0 z-40">
        <div className="max-w-6xl mx-auto px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <span className="font-mono text-sm neon-text-pink tracking-widest border border-neon-pink/50 px-2 py-0.5 shrink-0">
                ADMIN
              </span>
              <span className="font-mono text-lg neon-text-pink tracking-widest hidden sm:inline">
                EG&apos;OKE
              </span>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs text-white/50 hidden sm:inline truncate max-w-[10rem]">
                {user?.display_name}
              </span>
              <Link
                href="/"
                className="text-xs font-mono text-neon-blue border border-neon-blue/40 px-2 py-1 rounded hover:bg-neon-blue/10 transition-colors whitespace-nowrap"
              >
                ออกจากโหมด Admin
              </Link>
            </div>
          </div>

          <nav className="flex gap-1 overflow-x-auto no-scrollbar mt-2 -mb-1">
            {adminNav.map((n) => {
              // /admin ต้อง match แบบเป๊ะ ไม่งั้นมันจะ active ทุกหน้าย่อย
              const active = n.href === "/admin" ? pathname === "/admin" : pathname?.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  className={`px-3 py-1.5 text-sm whitespace-nowrap rounded-t transition-colors ${
                    active
                      ? "neon-text-pink border-b-2 border-neon-pink"
                      : n.external
                        // หน้าสแกนออกจากโหมด admin ไปจอเต็ม — ทำให้ต่างจากแท็บอื่นชัดๆ
                        ? "text-neon-green border border-neon-green/40 rounded"
                        : "text-white/50 hover:text-white"
                  }`}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-6xl w-full mx-auto px-4 py-6">{children}</main>

      <footer className="border-t border-neon-pink/20 py-3 text-center text-xs text-white/25 font-mono">
        EG&apos;OKE 2026 — โหมดผู้ดูแลระบบ
      </footer>
    </div>
  );
}
