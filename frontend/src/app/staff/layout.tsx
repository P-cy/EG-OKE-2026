"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { ProtectedRoute } from "@/components/ProtectedRoute";

// โซน staff — คนอยู่หน้างานทำได้แค่ 3 อย่าง
//
// ★ ทำไมต้องแยกจาก /admin:
//   staff งานนี้เป็นนักศึกษาอาสาหลายสิบคน เอาหน้า admin ไปให้ใช้ทั้งชุด
//   = ใครก็กดปรับเหรียญ ลบกิจกรรม เปิดโหมดปิดปรับปรุงได้หมด
//   ตรงนี้จึงมีแค่ทางเข้าที่ staff ต้องใช้จริง และ backend ก็กันอีกชั้น (require_staff)
//
// ★ สีเขียว — ต่างจากผู้ใช้ (น้ำเงิน) และ admin (ชมพู) กันคนสับสนว่าอยู่โหมดไหน
const staffNav = [
  { href: "/staff", label: "หน้าหลัก" },
  { href: "/scan", label: "สแกน QR", external: true },
  { href: "/staff/attendees", label: "ค้นรายชื่อ" },
];

export default function StaffLayout({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute roles={["staff", "admin"]}>
      <StaffChrome>{children}</StaffChrome>
    </ProtectedRoute>
  );
}

function StaffChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, hasRole } = useAuth();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="retro-panel border-b-2 border-neon-green/50 backdrop-blur sticky top-0 z-40">
        <div className="max-w-4xl mx-auto px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <span className="font-mono text-sm text-neon-green tracking-widest border border-neon-green/50 px-2 py-0.5 shrink-0">
                STAFF
              </span>
              <span className="font-mono text-lg neon-text-pink tracking-widest hidden sm:inline">
                EG&apos;OKE
              </span>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs text-white/50 hidden sm:inline truncate max-w-[10rem]">
                {user?.display_name}
              </span>
              {/* admin เข้าโซนนี้ได้ด้วย — ให้ทางกลับไปโหมดตัวเอง */}
              {hasRole("admin") && (
                <Link
                  href="/admin"
                  className="text-xs font-mono text-neon-pink border border-neon-pink/40 px-2 py-1 rounded hover:bg-neon-pink/10 transition-colors whitespace-nowrap"
                >
                  Admin
                </Link>
              )}
              <Link
                href="/"
                className="text-xs font-mono text-neon-blue border border-neon-blue/40 px-2 py-1 rounded hover:bg-neon-blue/10 transition-colors whitespace-nowrap"
              >
                ออกจากโหมด Staff
              </Link>
            </div>
          </div>

          <nav className="flex gap-1 overflow-x-auto no-scrollbar mt-2 -mb-1">
            {staffNav.map((n) => {
              const active = n.href === "/staff" ? pathname === "/staff" : pathname?.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  className={`px-3 py-1.5 text-sm whitespace-nowrap rounded-t transition-colors ${
                    active
                      ? "text-neon-green border-b-2 border-neon-green"
                      : n.external
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

      <main className="flex-1 max-w-4xl w-full mx-auto px-4 py-6">{children}</main>

      <footer className="border-t border-neon-green/20 py-3 text-center text-xs text-white/25 font-mono">
        EG&apos;OKE 2026 — โหมดเจ้าหน้าที่
      </footer>
    </div>
  );
}
