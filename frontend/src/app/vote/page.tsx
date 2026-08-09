"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, newIdemKey, type VoteRound } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { toast } from "@/components/Toaster";
import { countdown } from "@/lib/format";

export default function VotePage() {
  return (
    <ProtectedRoute>
      <VoteContent />
    </ProtectedRoute>
  );
}

type Pending = { round: VoteRound; artistId: string; artistName: string };

function VoteContent() {
  const qc = useQueryClient();
  const { data: rounds, isLoading } = useQuery({
    queryKey: ["rounds"],
    queryFn: () => api.listRounds(),
    refetchInterval: 5000,
  });
  // ตัวที่รอยืนยัน — โหวตเป็นของที่กดแล้วเปลี่ยนใจไม่ได้ ต้องถามก่อน
  const [pending, setPending] = useState<Pending | null>(null);

  const voteMut = useMutation({
    mutationFn: ({ round, artist }: { round: string; artist: string }) =>
      api.castVote(round, artist, newIdemKey()),
    onSuccess: (data) => {
      toast(data.already_voted ? "รอบนี้คุณโหวตไปแล้ว" : "โหวตสำเร็จ", "success");
      qc.invalidateQueries({ queryKey: ["rounds"] });
      setPending(null);
    },
    onError: (e: any) => {
      toast(e.message || "โหวตไม่สำเร็จ", "error");
      setPending(null);
    },
  });

  if (isLoading) return <div className="flex justify-center py-10"><Spinner /></div>;

  const openRounds = (rounds || []).filter((r) => r.status === "open");

  return (
    <div className="space-y-6">
      <h1 className="font-mono text-2xl neon-text-pink tracking-widest text-center">โหวตศิลปิน</h1>

      {openRounds.length === 0 && (
        <RetroCard glow="blue">
          <p className="text-center text-white/60">ยังไม่มีรอบโหวตที่เปิดอยู่ กรุณารอ MC ประกาศ</p>
        </RetroCard>
      )}

      {openRounds.map((r) => {
        // ★ โหวตได้ครั้งเดียวต่อรอบ — โหวตแล้วต้องล็อกทั้งรอบ
        //   ของเดิม disable เฉพาะปุ่มของวงที่เลือก วงอื่นยังกดได้
        //   กดไปก็ไม่เปลี่ยนอะไร (backend กันไว้) แต่ผู้ใช้เข้าใจผิดว่าเปลี่ยนใจได้
        const locked = !!r.my_vote;
        const chosen = r.candidates.find((c) => c.id === r.my_vote);

        return (
          <div key={r.round_key}>
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <div>
                <h2 className="font-mono text-lg neon-text-blue">{r.title}</h2>
                {r.closes_at && (
                  <p className="text-xs text-neon-yellow">
                    ปิดใน {countdown((new Date(r.closes_at).getTime() - Date.now()) / 1000)}
                  </p>
                )}
              </div>
              <span className="text-xs font-mono px-2 py-1 border border-white/20 text-white/50">
                โหวตได้ 1 ครั้ง
              </span>
            </div>

            {locked && (
              <div className="retro-panel neon-border-pink rounded p-3 mb-3 text-center">
                <p className="text-sm text-white/60">คุณโหวตให้</p>
                <p className="font-mono text-xl neon-text-pink">{chosen?.name || "ศิลปินที่เลือกไว้"}</p>
                <p className="text-xs text-white/40 mt-1">รอบนี้เปลี่ยนใจไม่ได้แล้ว</p>
              </div>
            )}

            <div className="grid sm:grid-cols-2 gap-3">
              {[...r.candidates]
                .sort((a, b) => a.sort_order - b.sort_order)
                .map((c) => {
                  const isMine = r.my_vote === c.id;
                  return (
                    <RetroCard key={c.id} glow={isMine ? "pink" : "blue"}>
                      <div className={`flex items-center gap-3 ${locked && !isMine ? "opacity-40" : ""}`}>
                        {c.image_url && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={c.image_url} alt={c.name} className="w-16 h-16 rounded object-cover neon-border-pink" />
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="font-bold text-white truncate">{c.name}</p>
                          {isMine && <p className="text-xs text-neon-pink">โหวตแล้ว</p>}
                        </div>
                        <NeonButton
                          variant={isMine ? "ghost" : "pink"}
                          disabled={locked}
                          onClick={() => setPending({ round: r, artistId: c.id, artistName: c.name })}
                        >
                          {isMine ? "เลือกแล้ว" : locked ? "-" : "โหวต"}
                        </NeonButton>
                      </div>
                    </RetroCard>
                  );
                })}
            </div>
          </div>
        );
      })}

      {(rounds || []).filter((r) => r.results_public).length > 0 && (
        <RetroCard glow="purple" title="ผลโหวต">
          <div className="space-y-2">
            {(rounds || []).filter((r) => r.results_public).map((r) => (
              <ResultBlock key={r.round_key} roundKey={r.round_key} title={r.title} />
            ))}
          </div>
        </RetroCard>
      )}

      {pending && (
        <ConfirmVote
          artistName={pending.artistName}
          roundTitle={pending.round.title}
          busy={voteMut.isPending}
          onCancel={() => setPending(null)}
          onConfirm={() =>
            voteMut.mutate({ round: pending.round.round_key, artist: pending.artistId })
          }
        />
      )}
    </div>
  );
}

function ConfirmVote({
  artistName, roundTitle, busy, onConfirm, onCancel,
}: {
  artistName: string; roundTitle: string; busy: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[80] bg-black/80 flex items-center justify-center p-4">
      <div className="retro-panel scanlines neon-border-pink rounded-lg max-w-sm w-full p-6 text-center">
        <p className="text-xs font-mono text-white/40 tracking-widest">{roundTitle}</p>
        <p className="text-white/70 mt-4">ยืนยันโหวตให้</p>
        <p className="font-mono text-2xl neon-text-pink mt-1 break-words">{artistName}</p>
        <p className="text-sm text-neon-yellow mt-4">
          โหวตได้ครั้งเดียวต่อรอบ กดแล้วเปลี่ยนใจไม่ได้
        </p>
        <div className="flex gap-3 mt-6">
          <NeonButton variant="ghost" onClick={onCancel} className="flex-1">
            ยกเลิก
          </NeonButton>
          <NeonButton variant="pink" loading={busy} onClick={onConfirm} className="flex-1">
            ยืนยันโหวต
          </NeonButton>
        </div>
      </div>
    </div>
  );
}

function ResultBlock({ roundKey, title }: { roundKey: string; title: string }) {
  const { data } = useQuery({
    queryKey: ["results", roundKey],
    queryFn: () => api.getResults(roundKey),
    refetchInterval: 3000,
  });
  if (!data) return null;
  const max = Math.max(...data.results.map((r) => r.votes), 1);
  return (
    <div>
      <p className="text-sm text-white/60 mb-2">{title} — รวม {data.total_votes} โหวต</p>
      <div className="space-y-1.5">
        {data.results.map((r) => (
          <div key={r.artist_id} className="flex items-center gap-2">
            <span className="text-xs text-white/70 w-24 truncate">{r.name}</span>
            <div className="flex-1 bg-bg-deep h-5 neon-border-blue overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-neon-purple to-neon-pink"
                style={{ width: `${(r.votes / max) * 100}%` }}
              />
            </div>
            <span className="font-mono text-xs neon-text-yellow w-12 text-right">{r.votes}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
