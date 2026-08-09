"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type VoteRound } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { toast } from "@/components/Toaster";
import { formatDateTime } from "@/lib/format";

// คุมรอบโหวตบนเวที — ต้องกดสดตอนพิธีกรประกาศ
//   เปิด   → รอบโผล่ในหน้า /vote ของทุกคน
//   ปิด    → หยุดรับโหวต + freeze คะแนนลง Mongo เป็นผลทางการ
//   ประกาศ → เปิดให้ทุกคนเห็นคะแนน
export default function AdminRoundsPage() {
  return (
    <ProtectedRoute roles={["admin"]}>
      <RoundsControl />
    </ProtectedRoute>
  );
}

function RoundsControl() {
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["admin-rounds"],
    queryFn: () => api.listRounds(),
    refetchInterval: 5000,
  });

  const controlMut = useMutation({
    mutationFn: ({ key, action }: { key: string; action: "open" | "close" | "publish" }) =>
      api.adminControlRound(key, action),
    onSuccess: (_res, v) => {
      toast(
        { open: "เปิดรอบโหวตแล้ว", close: "ปิดรอบแล้ว คะแนนถูกบันทึกเป็นผลทางการ", publish: "ประกาศผลแล้ว" }[v.action],
        "success",
      );
      qc.invalidateQueries({ queryKey: ["admin-rounds"] });
      qc.invalidateQueries({ queryKey: ["rounds"] });
    },
    onError: (e: any) => toast(e.message || "สั่งงานไม่สำเร็จ", "error"),
  });

  const rounds = data ?? [];

  return (
    <div className="space-y-6">
      <h1 className="font-mono text-2xl neon-text-pink tracking-widest text-center">คุมรอบโหวต</h1>

      <RetroCard glow="blue">
        <div className="text-sm text-white/60 space-y-1">
          <p><span className="text-neon-green font-mono">เปิด</span> — รอบโผล่ในหน้าโหวตของทุกคนทันที</p>
          <p><span className="text-neon-yellow font-mono">ปิด</span> — หยุดรับโหวต และบันทึกคะแนนตอนนั้นเป็นผลทางการ</p>
          <p><span className="text-neon-pink font-mono">ประกาศผล</span> — เปิดให้ผู้เข้างานเห็นคะแนน</p>
        </div>
      </RetroCard>

      {isLoading ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : rounds.length === 0 ? (
        <RetroCard glow="blue">
          <p className="text-center text-white/50 py-4">
            ยังไม่มีรอบโหวตในระบบ — ต้อง seed ข้อมูลรอบโหวตก่อน
          </p>
        </RetroCard>
      ) : (
        <div className="space-y-3">
          {rounds.map((r) => (
            <RoundCard
              key={r.round_key}
              round={r}
              onAction={(action) => controlMut.mutate({ key: r.round_key, action })}
              busy={controlMut.isPending && controlMut.variables?.key === r.round_key}
            />
          ))}
        </div>
      )}
    </div>
  );
}

const STATUS_UI: Record<string, { label: string; cls: string }> = {
  open:      { label: "เปิดรับโหวตอยู่", cls: "border-neon-green/50 text-neon-green" },
  scheduled: { label: "ยังไม่ถึงเวลาเปิด", cls: "border-neon-blue/50 text-neon-blue" },
  closed:    { label: "ปิดแล้ว",          cls: "border-neon-yellow/50 text-neon-yellow" },
  published: { label: "ประกาศผลแล้ว",     cls: "border-neon-pink/50 text-neon-pink" },
  draft:     { label: "ร่าง",             cls: "border-white/20 text-white/40" },
};

function RoundCard({
  round, onAction, busy,
}: {
  round: VoteRound;
  onAction: (a: "open" | "close" | "publish") => void;
  busy: boolean;
}) {
  const ui = STATUS_UI[round.status] ?? STATUS_UI.draft;
  const isOpen = round.status === "open";

  return (
    <RetroCard glow={isOpen ? "pink" : "blue"}>
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <p className="text-white font-medium">{round.title || round.round_key}</p>
            <p className="text-xs text-white/40 font-mono">{round.round_key}</p>
          </div>
          <span className={`text-xs px-2 py-1 border font-mono whitespace-nowrap ${ui.cls}`}>
            {ui.label}
          </span>
        </div>

        <div className="text-xs text-white/40 space-y-0.5 font-mono">
          {round.opens_at && <p>เปิด: {formatDateTime(round.opens_at)}</p>}
          {round.closes_at && <p>ปิด: {formatDateTime(round.closes_at)}</p>}
          <p>ผู้เข้าแข่ง {round.candidates.length} คน · ผลสาธารณะ: {round.results_public ? "เห็นแล้ว" : "ยังซ่อน"}</p>
        </div>

        {/* ★ เตือนกรณีที่เคยทำให้ผู้ใช้กดโหวตแล้ว error:
            status ยัง open แต่นาฬิกาเลยเวลาปิดไปแล้ว */}
        {round.status === "closed" && round.closes_at &&
          new Date(round.closes_at).getTime() < Date.now() && (
            <p className="text-xs text-neon-yellow">
              รอบนี้หมดเวลาตามนาฬิกาแล้ว — กด &quot;เปิดรอบ&quot; จะยังโหวตไม่ได้จนกว่าจะแก้เวลาปิดใน DB
            </p>
          )}

        <div className="flex gap-2 flex-wrap">
          <NeonButton
            variant={isOpen ? "ghost" : "pink"}
            loading={busy}
            disabled={isOpen}
            onClick={() => onAction("open")}
          >
            เปิดรอบ
          </NeonButton>
          <NeonButton
            variant="ghost"
            loading={busy}
            disabled={round.status === "published"}
            onClick={() => {
              if (confirm(`ปิดรอบ "${round.title}" — คะแนนตอนนี้จะถูกบันทึกเป็นผลทางการ ยืนยัน?`)) {
                onAction("close");
              }
            }}
          >
            ปิดรอบ
          </NeonButton>
          <NeonButton
            variant="blue"
            loading={busy}
            disabled={round.results_public}
            onClick={() => onAction("publish")}
          >
            {round.results_public ? "ประกาศแล้ว" : "ประกาศผล"}
          </NeonButton>
        </div>

        {round.candidates.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {round.candidates.map((c) => (
              <span key={c.id} className="text-[11px] px-2 py-0.5 border border-white/15 text-white/50">
                {c.name}
              </span>
            ))}
          </div>
        )}
      </div>
    </RetroCard>
  );
}
