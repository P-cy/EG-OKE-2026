"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { Spinner } from "@/components/Spinner";
import { formatCoins } from "@/lib/format";

export default function AdminDashboardPage() {
  return (
    <ProtectedRoute roles={["admin"]}>
      <DashboardContent />
    </ProtectedRoute>
  );
}

function DashboardContent() {
  const { data, isLoading } = useQuery({
    queryKey: ["admin-dashboard"],
    queryFn: () => api.adminDashboard(),
    refetchInterval: 5000,
  });

  if (isLoading) return <div className="flex justify-center py-10"><Spinner /></div>;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <h1 className="font-mono text-2xl neon-text-pink tracking-widest text-center">แดชบอร์ดเจ้าหน้าที่</h1>

      <section className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Tile label="ผู้ใช้ทั้งหมด" value={data.users.total} />
        <Tile label="ใช้งานอยู่" value={data.users.active} />
        <Tile label="เช็คอินวันนี้" value={data.checkins.today} />
        <Tile label="เช็คอินรวม" value={data.checkins.total} />
        <Tile label="โหวตรวม" value={data.votes.total} />
        <Tile label="คิวโหวตรอเขียน" value={data.votes.stream_pending} />
        <Tile label="คิว IG รอตรวจ" value={data.ig.pending} highlight />
        <Tile label="IG อนุมัติแล้ว" value={data.ig.approved} />
        <Tile label="หมุนวงล้อ" value={data.spins} />
      </section>

      <RetroCard glow="purple" title="ลำดับความสำคัญหน้างาน">
        <ol className="text-sm text-white/70 space-y-1 list-decimal list-inside">
          <li>เปิดคิว IG ดูรายการที่รอตรวจที่หน้า "คิว IG"</li>
          <li>ปิด/เปิดรอบโหวตตามจังหวะ MC ประกาศ</li>
          <li>หากมีปัญหาระบบ ไปที่หน้า "ฉุกเฉิน" ปิดฟีเจอร์ได้ทันที</li>
        </ol>
      </RetroCard>
    </div>
  );
}

function Tile({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className={`retro-panel scanlines rounded-md p-4 text-center ${highlight ? "neon-border-pink" : "neon-border-blue"}`}>
      <p className="text-xs text-white/50">{label}</p>
      <p className={`font-mono text-2xl mt-1 ${highlight ? "neon-text-pink" : "neon-text-blue"}`}>{formatCoins(value)}</p>
    </div>
  );
}
