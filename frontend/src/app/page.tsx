"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { formatCoins } from "@/lib/format";

export default function HomePage() {
  const { user } = useAuth();
  // สถานะระบบสด — poll ทุก 3 วิ แต่หยุดเมื่อ tab ซ่อน
  const snap = useQuery({
    queryKey: ["snapshot"],
    queryFn: () => api.getSnapshot(),
    refetchInterval: (q) =>
      typeof document !== "undefined" && document.hidden ? false : 3000 + Math.random() * 500,
  });

  const ann = snap.data?.announcement;

  return (
    <div className="space-y-6">
      <section className="text-center py-8">
        <h1 className="font-mono text-4xl sm:text-6xl neon-text-pink tracking-widest animate-flicker">
          EG'OKE 2026
        </h1>
        <p className="mt-3 text-white/60 font-mono text-sm">RETRO SYNTHWAVE EDITION</p>
      </section>

      {ann?.text && (
        <div className={`retro-panel scanlines p-4 text-center ${
          ann.level === "warn" ? "neon-border-pink" : "neon-border-blue"
        }`}>
          <p className="font-medium">{ann.text}</p>
        </div>
      )}

      {user?.needs_onboarding && (
        <RetroCard glow="pink" title="ต้องตั้งค่าก่อน">
          <p className="text-white/70 mb-4">กรอกชื่อเล่นและคณะ/ภาคเพื่อเริ่มใช้งานให้ครบ</p>
          <Link href="/onboarding">
            <NeonButton variant="pink">เริ่มตั้งค่า</NeonButton>
          </Link>
        </RetroCard>
      )}

      {snap.isLoading ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : snap.data ? (
        <section className="grid grid-cols-3 gap-3">
          <StatTile label="คนเข้างานวันนี้" value={snap.data.checkins?.today ?? 0} />
          <StatTile label="โหวตรวม" value={snap.data.active_round?.tally?.reduce((a, b) => a + b.votes, 0) ?? 0} />
          <StatTile label="คิว IG" value={snap.data.features?.ig_submission ? "เปิด" : "ปิด"} />
        </section>
      ) : null}

      <section className="grid sm:grid-cols-2 gap-4">
        <Link href="/vote">
          <RetroCard glow="pink" title="โหวตศิลปิน">
            <p className="text-white/70 text-sm">เลือกศิลปินในรอบปัจจุบัน</p>
          </RetroCard>
        </Link>
        <Link href="/ig">
          <RetroCard glow="purple" title="ส่งโพสต์ Instagram">
            <p className="text-white/70 text-sm">แลกcoin และขึ้นจอใหญ่หน้างาน</p>
          </RetroCard>
        </Link>
        <Link href="/wheel">
          <RetroCard glow="blue" title="วงล้อรางวัล">
            <p className="text-white/70 text-sm">ใช้coinหมุนรับรางวัล</p>
          </RetroCard>
        </Link>
        <Link href="/ticket">
          <RetroCard glow="purple" title="บัตรเข้างาน QR">
            <p className="text-white/70 text-sm">แสดงบัตรที่ประตูเข้างาน</p>
          </RetroCard>
        </Link>
      </section>

      {user && (
        <RetroCard glow="blue">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-white/60 text-xs">coin</p>
              <p className="font-mono text-3xl neon-text-yellow">{formatCoins(user.coins_balance)}</p>
            </div>
            <Link href="/points">
              <NeonButton variant="blue">ดูประวัติ</NeonButton>
            </Link>
          </div>
        </RetroCard>
      )}
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="retro-panel scanlines neon-border-blue rounded-md p-4 text-center">
      <p className="text-xs text-white/50">{label}</p>
      <p className="font-mono text-2xl neon-text-blue mt-1">{value}</p>
    </div>
  );
}
