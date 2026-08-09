"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Spinner } from "@/components/Spinner";
import { formatCoins } from "@/lib/format";

// จอผลโหวตสด — bar chart ใหญ่ อ่านจากระยะ 20 เมตร
export default function DisplayVotePage() {
  const { data, isLoading } = useQuery({
    queryKey: ["snapshot"],
    queryFn: () => api.getSnapshot(),
    refetchInterval: (q) =>
      typeof document !== "undefined" && document.hidden ? false : 1000,
  });

  if (isLoading) return <div className="flex justify-center items-center min-h-screen"><Spinner size={60} /></div>;

  const round = data?.active_round;
  if (!round) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="font-mono text-5xl text-white/40">ยังไม่มีรอบโหวต</p>
      </div>
    );
  }

  const tally = round.tally || [];
  const max = Math.max(...tally.map((t) => t.votes), 1);

  return (
    <div className="min-h-screen p-10 flex flex-col">
      <header className="text-center mb-10">
        <h1 className="font-mono text-6xl neon-text-pink tracking-widest animate-flicker">
          {round.status === "open" ? "ผลโหวตสด" : "ผลโหวต"}
        </h1>
        {round.closes_in != null && round.status === "open" && (
          <p className="text-2xl text-neon-yellow font-mono mt-3">ปิดใน {Math.floor(round.closes_in / 60)}:{(round.closes_in % 60).toString().padStart(2, "0")}</p>
        )}
      </header>

      <div className="flex-1 flex flex-col justify-center gap-6 max-w-5xl mx-auto w-full">
        {tally
          .slice()
          .sort((a, b) => b.votes - a.votes)
          .map((t, i) => (
            <div key={t.artist_id} className="flex items-center gap-6">
              <span className="font-mono text-7xl neon-text-blue w-20 text-right">{i + 1}</span>
              <span className="text-4xl text-white w-64 truncate">{t.name}</span>
              <div className="flex-1 h-16 bg-bg-deep neon-border-blue overflow-hidden">
                <div
                  className="h-full transition-all duration-1000"
                  style={{
                    width: `${(t.votes / max) * 100}%`,
                    background: i === 0 ? "linear-gradient(90deg, #ff2d95, #ffe600)"
                      : i === 1 ? "linear-gradient(90deg, #b026ff, #00e5ff)"
                      : "linear-gradient(90deg, #00e5ff, #b026ff)",
                  }}
                />
              </div>
              <span className="font-mono text-6xl neon-text-yellow w-40 text-right">{formatCoins(t.votes)}</span>
            </div>
          ))}
      </div>

      <footer className="text-center text-white/30 font-mono mt-10">
        EG'OKE 2026 — {round.results_public ? "ผลเปิดเผย" : "ผลซ่อนไว้"}
      </footer>
    </div>
  );
}
