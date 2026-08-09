"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";

const userNav = [
  { href: "/", label: "หน้าหลัก" },
  { href: "/quests", label: "กิจกรรม" },
  { href: "/vote", label: "โหวต" },
  { href: "/ig", label: "ส่ง IG" },
  { href: "/points", label: "coin" },
  { href: "/wheel", label: "วงล้อ" },
  { href: "/ticket", label: "บัตร" },
  { href: "/profile", label: "โปรไฟล์" },
];

// ★ nav ของ admin ย้ายไปอยู่ใน app/admin/layout.tsx แล้ว
//   ของเดิมเอามาต่อท้าย nav ผู้ใช้ในแถบเดียวกัน = 15 ปุ่มเลื่อนไม่จบบนมือถือ
//   ตรงนี้เหลือแค่ปุ่มเดียวไว้เข้าโหมด admin

// หน้าที่ไม่ต้อง login — public
const PUBLIC_PATHS = ["/login"];

export function Layout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout, hasRole, hydrated, refreshUser } = useAuth();
  const isAdmin = hasRole("admin");
  const isStaff = hasRole("staff");
  const isDisplay = pathname?.startsWith("/display");
  const isScan = pathname?.startsWith("/scan");
  // ★ /admin/* กับ /staff/* มี layout ของตัวเอง — ตรงนี้ต้องไม่ครอบซ้ำ
  //   ไม่งั้นจะได้ header สองชั้นซ้อนกัน
  const hasOwnLayout = pathname?.startsWith("/admin") || pathname?.startsWith("/staff");
  const isPublic = PUBLIC_PATHS.includes(pathname || "");

  // ★ บังคับ login ก่อนเข้าเว็บ — ถ้ายังไม่ login และไม่ใช่หน้า public → ไป /login
  useEffect(() => {
    if (!hydrated) return;
    const token = typeof window !== "undefined" && localStorage.getItem("access_token");
    if (!token && !isPublic && !isDisplay && !isScan) {
      router.replace("/login");
    }
  }, [hydrated, isPublic, isDisplay, isScan, router]);

  // ★ ข้อมูลโปรไฟล์ยังไม่ครบ → พากลับไปกรอก
  //   ของเดิมเช็คตอน login อย่างเดียว แปลว่าคนมหิดลที่ผ่าน onboarding
  //   ไปแล้วก่อนระบบจะบังคับกรอกคณะ จะไม่มีอะไรพากลับมากรอกเลย
  //   (backend คืน needs_onboarding=true ให้เอง ถ้าคนมหิดลยังไม่มีคณะ/รหัสนักศึกษา)
  //   ★ เฉพาะหน้าฝั่งผู้ใช้ — ห้ามเด้ง staff ที่กำลังสแกนอยู่หน้าประตูออกจากงาน
  //     (hook ทำงานทุกหน้าแม้ Layout จะ return children ตรงๆ ไปแล้ว)
  useEffect(() => {
    if (!hydrated || !user?.needs_onboarding) return;
    if (isDisplay || isScan || hasOwnLayout || isPublic) return;
    if (pathname === "/onboarding") return;
    router.replace("/onboarding");
  }, [hydrated, user?.needs_onboarding, pathname, isDisplay, isScan, hasOwnLayout, isPublic, router]);

  // ★ refresh ยอดcoinล่าสุดทุกครั้งที่กลับเข้าหน้าเว็บ (focus tab / สลับหน้า)
  //   กัน auth store เก็บยอดเก่าตอน admin topupให้ที่อื่น
  useEffect(() => {
    const token = typeof window !== "undefined" && localStorage.getItem("access_token");
    if (!token) return;
    const onFocus = () => refreshUser();
    document.addEventListener("visibilitychange", onFocus);
    window.addEventListener("focus", onFocus);
    return () => {
      document.removeEventListener("visibilitychange", onFocus);
      window.removeEventListener("focus", onFocus);
    };
  }, [refreshUser]);

  // เปลี่ยนหน้า → refresh ยอดทันที (admin เติมในหน้า users แล้วกลับมาหน้า home ต้องเห็นยอดใหม่)
  useEffect(() => {
    const token = typeof window !== "undefined" && localStorage.getItem("access_token");
    if (token) refreshUser();
  }, [pathname, refreshUser]);

  // จอ display + scanner ไม่มี nav
  if (isDisplay || isScan) return <>{children}</>;

  // โซน admin มี layout ของตัวเอง — ปล่อยผ่านไปเลย
  if (hasOwnLayout) return <>{children}</>;

  // หน้า public (login) ไม่มี nav
  if (isPublic) return <>{children}</>;

  // ยังไม่ login หรือกำลัง redirect — โชว์ loading ไม่ใช่เนื้อหา
  if (!hydrated || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-white/40 font-mono">กำลังโหลด...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="retro-panel border-b border-neon-purple/30 backdrop-blur sticky top-0 z-40">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between gap-2">
          <Link href="/" className="font-mono text-xl neon-text-pink tracking-widest">
            EG'OKE
          </Link>
          <nav className="flex gap-1 overflow-x-auto no-scrollbar">
            {userNav.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={`px-3 py-1.5 text-sm whitespace-nowrap rounded transition-colors ${
                  pathname === n.href
                    ? "neon-text-blue border-b-2 border-neon-blue"
                    : "text-white/60 hover:text-white"
                }`}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-2 shrink-0">
            <div className="text-right text-xs hidden sm:block">
              <p className="text-white/80 font-medium">{user.display_name}</p>
              <p className="text-neon-yellow font-mono">
                {(user.coins_balance ?? 0).toLocaleString("th-TH")} coin
              </p>
            </div>
            {/* ★ ทางเข้าโหมด staff/admin — ปุ่มเดียว ไม่ใช่ nav ทั้งชุดปนกับของผู้ใช้
                staff ที่ไม่ใช่ admin เห็นแค่ปุ่ม Staff (หน้า admin เข้าไม่ได้อยู่แล้ว) */}
            {isStaff && !isAdmin && (
              <Link
                href="/staff"
                className="text-xs font-mono text-neon-green border border-neon-green/40 px-2 py-1 rounded hover:bg-neon-green/10 transition-colors whitespace-nowrap"
              >
                Staff
              </Link>
            )}
            {isAdmin && (
              <Link
                href="/admin"
                className="text-xs font-mono text-neon-pink border border-neon-pink/40 px-2 py-1 rounded hover:bg-neon-pink/10 transition-colors whitespace-nowrap"
              >
                Admin
              </Link>
            )}
            <button
              onClick={logout}
              className="text-xs text-white/40 hover:text-white border border-white/20 px-2 py-1 rounded transition-colors"
            >
              ออก
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-6">{children}</main>

      <footer className="border-t border-neon-purple/20 py-4 text-center text-xs text-white/30 font-mono">
        EG'OKE 2026 — retro synthwave edition
      </footer>
    </div>
  );
}
