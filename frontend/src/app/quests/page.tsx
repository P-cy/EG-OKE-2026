"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, type Quest } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { useAuth } from "@/lib/auth";
import { formatCoins } from "@/lib/format";

// หน้ากิจกรรม — คนเข้างานดูว่ามีบูธอะไร ได้เหรียญเท่าไหร่ ทำไปแล้วอันไหน
// วิธีรับ: เดินไปบูธ เปิดหน้าบัตร QR ให้ staff สแกน
export default function QuestsPage() {
  return (
    <ProtectedRoute>
      <QuestsContent />
    </ProtectedRoute>
  );
}

function QuestsContent() {
  const user = useAuth((s) => s.user);
  const { data, isLoading } = useQuery({
    queryKey: ["quests"],
    queryFn: () => api.listQuests(),
    refetchInterval: (q) =>
      typeof document !== "undefined" && document.hidden ? false : 15_000,
  });

  const quests = data ?? [];
  const done = quests.filter((q) => q.my_claims >= q.max_per_user).length;
  const earned = quests.reduce((sum, q) => sum + q.coins * q.my_claims, 0);

  return (
    <div className="space-y-6">
      <h1 className="font-mono text-2xl neon-text-pink tracking-widest text-center">
        กิจกรรมรับเหรียญ
      </h1>

      {/* สรุป + ทางไปบัตร (สิ่งที่ต้องเปิดให้ staff สแกน) */}
      <RetroCard glow="pink">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="space-y-0.5">
            <p className="text-xs text-white/50">ทำแล้ว {done} / {quests.length} กิจกรรม</p>
            <p className="font-mono text-2xl neon-text-yellow">
              +{formatCoins(earned)} coin จากกิจกรรม
            </p>
            <p className="text-xs text-white/40">
              ยอดรวมตอนนี้ {formatCoins(user?.coins_balance ?? 0)} coin
            </p>
          </div>
          <Link href="/ticket">
            <NeonButton variant="pink">เปิดบัตร QR</NeonButton>
          </Link>
        </div>
      </RetroCard>

      <RetroCard glow="blue">
        <p className="text-sm text-white/60">
          เดินไปที่บูธกิจกรรม เปิดหน้าบัตร QR ให้เจ้าหน้าที่สแกน แล้วเหรียญจะเข้าทันที
        </p>
      </RetroCard>

      {isLoading ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : quests.length === 0 ? (
        <RetroCard glow="blue">
          <p className="text-center text-white/50 py-4">
            ยังไม่มีกิจกรรมเปิดอยู่ — รอประกาศจากทีมงาน
          </p>
        </RetroCard>
      ) : (
        <div className="grid sm:grid-cols-2 gap-3">
          {quests.map((q) => <QuestCard key={q.quest_key} quest={q} />)}
        </div>
      )}
    </div>
  );
}

function QuestCard({ quest }: { quest: Quest }) {
  const complete = quest.my_claims >= quest.max_per_user;
  const partial = quest.my_claims > 0 && !complete;

  return (
    <RetroCard glow={complete ? "purple" : "blue"}>
      <div className="space-y-2">
        <div className="flex items-start justify-between gap-2">
          <p className={`font-medium ${complete ? "text-white/50 line-through" : "text-white"}`}>
            {quest.title}
          </p>
          <span className="font-mono text-neon-yellow whitespace-nowrap shrink-0">
            +{quest.coins}
          </span>
        </div>

        {quest.description && (
          <p className="text-xs text-white/50 whitespace-pre-wrap">{quest.description}</p>
        )}

        <div className="flex items-center gap-2 pt-1">
          {complete ? (
            <span className="text-xs px-2 py-1 border border-neon-green/40 text-neon-green font-mono">
              รับแล้ว
            </span>
          ) : (
            <span className="text-xs px-2 py-1 border border-white/20 text-white/40 font-mono">
              ยังไม่ได้รับ
            </span>
          )}
          {quest.max_per_user > 1 && (
            <span className="text-xs text-white/35 font-mono">
              {quest.my_claims}/{quest.max_per_user} ครั้ง
            </span>
          )}
          {partial && (
            <span className="text-xs text-neon-yellow font-mono">รับได้อีก</span>
          )}
        </div>
      </div>
    </RetroCard>
  );
}
