"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { Spinner } from "@/components/Spinner";
import { formatCoins, formatDateTime } from "@/lib/format";
import { useAuth } from "@/lib/auth";

export default function PointsPage() {
  return (
    <ProtectedRoute>
      <PointsContent />
    </ProtectedRoute>
  );
}

function PointsContent() {
  const { user } = useAuth();
  const { data, isLoading } = useQuery({
    queryKey: ["my-points"],
    queryFn: () => api.getMyPoints(),
  });

  return (
    <div className="space-y-6">
      <div className="text-center">
        <p className="text-white/50 text-sm">coin</p>
        <p className="font-mono text-5xl neon-text-pink animate-flicker">{formatCoins(user?.coins_balance ?? 0)}</p>
        {user?.rank && <p className="text-white/40 text-sm mt-1">อันดับที่ {user.rank}</p>}
      </div>

      <RetroCard glow="blue" title="coin history (Ledger)">
        {isLoading ? (
          <div className="flex justify-center py-6"><Spinner /></div>
        ) : data?.items?.length ? (
          <div className="space-y-2">
            {data.items.map((tx) => (
              <div key={tx.id} className="flex items-center justify-between border-b border-white/10 pb-2">
                <div>
                  <p className="text-sm text-white/80">{reasonLabel(tx.reason)}</p>
                  {tx.note && <p className="text-xs text-white/40">{tx.note}</p>}
                  <p className="text-xs text-white/30">{formatDateTime(tx.created_at)}</p>
                </div>
                <p className={`font-mono text-lg ${tx.amount >= 0 ? "neon-text-blue" : "text-red-400"}`}>
                  {tx.amount >= 0 ? "+" : ""}{tx.amount}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-white/40 text-sm text-center py-4">ยังไม่มีประวัติ</p>
        )}
      </RetroCard>
    </div>
  );
}

function reasonLabel(reason: string): string {
  const map: Record<string, string> = {
    checkin: "เช็คอินเข้างาน",
    instagram_approved: "โพสต์ IG ผ่านการอนุมัติ",
    vote_bonus: "โบนัสจากการโหวต",
    wheel_cost: "หมุนวงล้อ",
    wheel_prize: "รางวัลวงล้อ",
    admin_adjust: "adjust coinโดยเจ้าหน้าที่",
    referral: "เชิญเพื่อน",
    ig_wall: "ขึ้นจอ IG",
    topup: "topup",
  };
  return map[reason] || reason;
}
