"use client";

import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, newIdemKey } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { Spinner } from "@/components/Spinner";
import { toast } from "@/components/Toaster";
import { formatCoins } from "@/lib/format";

export default function WheelPage() {
  return (
    <ProtectedRoute>
      <SlotContent />
    </ProtectedRoute>
  );
}

// สัญลักษณ์บนรีล — ใช้ emoji แบบ classic slot machine
function labelSymbol(label: string): string {
  const s = label.toLowerCase();
  if (s.includes("100")) return "💎";
  if (s.includes("50")) return "⭐";
  if (s.includes("10")) return "🔔";
  if (s.includes("เสื้อ") || s.includes("shirt")) return "🎁";
  if (s.includes("ไม่ถูก") || s.includes("เสีย") || s.includes("lose") || s.includes("no") || s.includes("again")) return "✖";
  if (s.includes("jackpot") || s.includes("แจ็ค")) return "7️⃣";
  return "7️⃣";
}

// symbol ทั้งหมดที่จะวนบน strip (สุ่มตำแหน่ง)
const ALL_SYMBOLS = ["7️⃣", "💎", "⭐", "🔔", "🎁", "✖", "🍒", "🍋"];

function SlotContent() {
  const qc = useQueryClient();
  const { refreshUser } = useAuth();
  const [leverPulled, setLeverPulled] = useState(false);
  // ผลสุดท้ายแต่ละรีล (emoji) + state ของแต่ละรีล: idle | spinning | done
  const [results, setResults] = useState<[string, string, string] | null>(null);
  const [reelStates, setReelStates] = useState<["idle" | "spinning" | "done", "idle" | "spinning" | "done", "idle" | "spinning" | "done"]>(["idle", "idle", "idle"]);
  const [lastWon, setLastWon] = useState<number | null>(null);

  const { data: wheel, isLoading } = useQuery({
    queryKey: ["wheel", "main-wheel"],
    queryFn: () => api.getWheel("main-wheel"),
    refetchInterval: 10000,
  });

  const spinning = reelStates.some((s) => s === "spinning");

  const spinMut = useMutation({
    // ★ nonce = ครั้งที่เท่าไหร่ของคนนี้ (ไม่ใช่เลขสุ่ม)
    //   backend มี unique index (user_id, wheel_key, nonce) — ของเดิมสุ่ม 1..1000
    //   จึงชนกันเองได้ ~0.3% ต่อคน และตอนชนคือ "หักเหรียญไปแล้ว แต่การหมุนไม่ถูกบันทึก"
    //   งาน 5,000 คน = มีคนโดนจริงหลายสิบคน
    //   เลขเรียงลำดับยังทำให้กดสองแท็บพร้อมกันชน index ทันที = กันหมุนเกินโควตาไปในตัว
    mutationFn: (clientSeed: string) =>
      api.spinWheel("main-wheel", clientSeed, (wheel?.my_spins_used ?? 0) + 1, newIdemKey()),
    onSuccess: async (res) => {
      const seg = wheel?.segments[res.segment_index];
      const sym = labelSymbol(seg?.label || "7");
      const final: [string, string, string] = [sym, sym, sym];

      setLastWon(null);
      setResults(null);

      // ★ ทั้ง 3 รีลเริ่มหมุนพร้อมกัน
      setReelStates(["spinning", "spinning", "spinning"]);

      // หยุดทีละตัว (left → right) เพิ่ม suspense
      await delay(1600);
      setResults([final[0], "—", "—"]);
      setReelStates((s) => ["done", s[1], s[2]]);

      await delay(900);
      setResults([final[0], final[1], "—"]);
      setReelStates((s) => [s[0], "done", s[2]]);

      await delay(1200);
      setResults(final);
      setReelStates(["done", "done", "done"]);
      setLastWon(res.coins_won);
      toast(`คุณได้: ${seg?.label || res.label}`, res.coins_won > 0 ? "success" : "info");
      qc.invalidateQueries({ queryKey: ["wheel", "main-wheel"] });
      refreshUser();
    },
    onError: (e: any) => {
      setReelStates(["idle", "idle", "idle"]);
      toast(e.message || "หมุนไม่สำเร็จ", "error");
    },
  });

  function pullLever() {
    if (spinning) return;
    setLeverPulled(true);
    setTimeout(() => setLeverPulled(false), 350);
    const clientSeed = Math.random().toString(36).slice(2, 10);
    spinMut.mutate(clientSeed);
  }

  if (isLoading) return <div className="flex justify-center py-10"><Spinner /></div>;
  if (!wheel) return null;

  const canSpin = wheel.status === "open" && wheel.my_spins_left > 0 && wheel.my_coins >= wheel.cost_coins;
  const isWin = lastWon !== null && lastWon > 0;

  return (
    <div className="space-y-6">
      <h1 className="font-mono text-2xl neon-text-pink tracking-widest text-center">{wheel.title}</h1>

      <RetroCard glow="pink">
        <div className="grid grid-cols-3 gap-3 text-center mb-6">
          <div>
            <p className="text-xs text-white/50">your coin</p>
            <p className="font-mono text-xl neon-text-yellow">{formatCoins(wheel.my_coins)}</p>
          </div>
          <div>
            <p className="text-xs text-white/50">cost / spin</p>
            <p className="font-mono text-xl neon-text-pink">{wheel.cost_coins}</p>
          </div>
          <div>
            <p className="text-xs text-white/50">spins left</p>
            <p className="font-mono text-xl neon-text-blue">{wheel.my_spins_left}</p>
          </div>
        </div>

        {/* ★ ตู้สล็อต */}
        <div className="flex items-stretch justify-center gap-3 sm:gap-5">
          {/* ตัวตู้ */}
          <div className={`relative bg-gradient-to-b from-[#1a0a2e] to-bg-deep rounded-2xl p-4 sm:p-5 ${isWin ? "shadow-[0_0_60px_rgba(255,230,0,0.6)]" : "shadow-[0_0_40px_rgba(255,45,149,0.3)]"} border-2 ${isWin ? "border-neon-yellow" : "border-neon-pink"}`}>
            {/* หลังคาตู้ + ไฟวงรอบ */}
            <div className="flex justify-center gap-1 mb-3">
              {[...Array(7)].map((_, i) => (
                <span key={i} className={`w-2 h-2 rounded-full ${spinning ? "bg-neon-pink animate-pulse" : isWin ? "bg-neon-yellow" : "bg-neon-blue/40"}`} style={{ animationDelay: `${i * 0.1}s` }} />
              ))}
            </div>

            {/* รีล 3 ตัว */}
            <div className="flex gap-2 sm:gap-3 bg-black/70 p-2 sm:p-3 rounded-xl border border-neon-purple/40">
              {[0, 1, 2].map((i) => (
                <Reel key={i} state={reelStates[i]} finalSymbol={results?.[i] ?? null} />
              ))}
            </div>

            {/* ป้ายผล */}
            <div className="h-8 mt-3 flex items-center justify-center">
              {lastWon !== null && !spinning && (
                <span className={`font-mono text-lg tracking-widest ${isWin ? "neon-text-yellow animate-flicker" : "text-white/40"}`}>
                  {isWin ? `★ WIN +${lastWon} ★` : "TRY AGAIN"}
                </span>
              )}
            </div>
          </div>

          {/* ★ คันโยก */}
          <div className="flex flex-col items-center justify-center">
            <button
              onClick={pullLever}
              disabled={!canSpin || spinning}
              className="relative flex flex-col items-center group disabled:opacity-30"
              aria-label="pull lever"
            >
              {/* ฐาน */}
              <div className="w-6 h-10 bg-gradient-to-b from-neon-purple/80 to-bg-deep rounded-md border border-neon-pink/50" />
              {/* ก้าน + หัวคันโยก */}
              <div
                className={`absolute left-1/2 -translate-x-1/2 origin-bottom transition-transform duration-300 ease-out ${leverPulled ? "rotate-[35deg]" : "-rotate-[15deg]"} group-hover:rotate-0 group-disabled:group-hover:-rotate-[15deg]`}
                style={{ bottom: "8px" }}
              >
                <div className="w-1.5 h-24 sm:h-28 bg-gradient-to-b from-neon-pink to-neon-purple rounded-full mx-auto" />
                <div className="w-7 h-7 -mt-1 rounded-full bg-gradient-to-br from-[#ff6b6b] to-neon-pink shadow-[0_0_20px_var(--neon-pink)] border-2 border-white/30 mx-auto" />
              </div>
            </button>
            <span className="text-[10px] font-mono text-neon-yellow mt-2 tracking-widest">PULL</span>
          </div>
        </div>

        {/* ปุ่มใหญ่สำรอง */}
        <div className="flex justify-center mt-6">
          <button
            onClick={pullLever}
            disabled={!canSpin || spinning}
            className="font-mono text-base px-10 py-3 rounded-lg neon-border-pink bg-bg-deep text-neon-pink disabled:opacity-40 hover:bg-neon-pink/10 transition-colors tracking-widest"
          >
            {spinning ? "◉ SPINNING" : wheel.status !== "open" ? "CLOSED" : wheel.my_spins_left <= 0 ? "NO SPINS" : `SPIN · ${wheel.cost_coins} coin`}
          </button>
        </div>
      </RetroCard>

      <RetroCard glow="blue" title="รางวัลที่เป็นไปได้">
        <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
          {wheel.segments.map((s) => (
            <div key={s.id} className={`text-center p-2 rounded border ${s.sold_out ? "opacity-30 border-white/10" : "border-white/20"}`}>
              <p className="text-3xl">{labelSymbol(s.label)}</p>
              <p className="text-xs text-white/60 mt-1">{s.label}</p>
              {s.sold_out && <p className="text-[10px] text-red-400">SOLD OUT</p>}
            </div>
          ))}
        </div>
      </RetroCard>

      <RetroCard glow="purple" title="Provably Fair">
        <p className="text-xs text-white/60">
          ผลตัดสินที่ server ด้วย HMAC-SHA256 — ไม่มีการสุ่มที่ frontend ตรวจสอบย้อนหลังได้ที่ /wheel/verify หลังงานจบ
        </p>
        <p className="text-xs text-neon-blue font-mono mt-2 break-all">commit: {wheel.commit_hash}</p>
      </RetroCard>
    </div>
  );
}

// ★ Reel — แถบยาว symbol เลื่อนลงเร็วๆ (motion blur) แล้วล็อกที่ผล
function Reel({ state, finalSymbol }: { state: "idle" | "spinning" | "done"; finalSymbol: string | null }) {
  // strip สุ่มคงที่ตลอดอายุ component — ตอนหมุนมันเบลอจนแยกไม่ออกอยู่แล้ว
  const stripRef = useRef<string[] | null>(null);
  if (stripRef.current === null) stripRef.current = makeStrip();
  const strip = stripRef.current;
  // state = spinning → blur + scroll ลง; done → ล็อกตรงกลาง
  const spinning = state === "spinning";

  return (
    <div className="w-14 h-20 sm:w-16 sm:h-24 bg-black rounded-lg overflow-hidden relative border border-neon-blue/40 flex items-center justify-center">
      {/* แถบ strip เลื่อน */}
      <div
        className="absolute inset-x-0 flex flex-col items-center"
        style={{
          transition: spinning ? "none" : "transform 0.3s ease-out",
          transform: spinning ? "translateY(0)" : "translateY(-50%)",
        }}
      >
        {spinning ? (
          // ตอนหมุน: แสดง symbol วนเร็วๆ + blur
          <div className="animate-[slot-scroll_0.3s_linear_infinite] py-1" style={{ filter: "blur(1.5px)" }}>
            {strip.map((s, i) => (
              <span key={i} className="text-3xl sm:text-4xl block py-0.5">{s}</span>
            ))}
          </div>
        ) : (
          // ตอนหยุด: ล็อก symbol ตรงกลาง
          <span className="text-4xl sm:text-5xl block py-2">{finalSymbol ?? "7️⃣"}</span>
        )}
      </div>

      {/* ไลน์บนล่าง (frame ตู้) */}
      <div className="absolute top-0 inset-x-0 h-3 bg-gradient-to-b from-black to-transparent pointer-events-none" />
      <div className="absolute bottom-0 inset-x-0 h-3 bg-gradient-to-t from-black to-transparent pointer-events-none" />

      {/* แสงตอนล็อกเสร็จ */}
      {state === "done" && finalSymbol && (
        <div className="absolute inset-0 bg-neon-yellow/5 pointer-events-none" />
      )}
    </div>
  );
}

// สร้าง strip symbol สุ่ม (ใช้ตอนหมุน)
function makeStrip(): string[] {
  return Array.from(
    { length: 12 },
    () => ALL_SYMBOLS[Math.floor(Math.random() * ALL_SYMBOLS.length)],
  );
}

function delay(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}
