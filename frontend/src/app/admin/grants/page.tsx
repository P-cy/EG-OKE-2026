"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type GrantSummary } from "@/lib/api";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { toast } from "@/components/Toaster";
import { formatCoins } from "@/lib/format";

// เฝ้าดูการจ่ายเหรียญของ staff
//
// ★ โควตากันได้แค่ "จ่ายเยอะเกินไปในวันเดียว" แต่กัน "จ่ายพอดีๆ ให้คนเดิมทุกวัน" ไม่ได้
//   สิ่งที่จับคนโกงได้จริงคือ **รูปแบบ** — ตัวเลขดิบไม่บอกอะไร
//   ต้องเรียงให้เห็นว่าใครโดดออกมาจากคนอื่น แล้วคนดูค่อยตัดสิน
// (ProtectedRoute roles=["admin"] ครอบมาจาก app/admin/layout.tsx แล้ว)
export default function AdminGrantsPage() {
  const qc = useQueryClient();
  const [hours, setHours] = useState(24);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["admin-grants", hours],
    queryFn: () => api.adminGrantSummary(hours),
    refetchInterval: 60_000,
  });

  const resetMut = useMutation({
    mutationFn: (staff_id: string) => api.adminResetGrantBudget(staff_id),
    onSuccess: (res) => {
      toast(`ล้างโควตาแล้ว (ใช้ไป ${res.cleared} เหรียญ)`, "success");
      qc.invalidateQueries({ queryKey: ["admin-grants"] });
    },
    onError: (e: any) => toast(e.message || "ล้างไม่สำเร็จ", "error"),
  });

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="font-mono text-2xl neon-text-pink tracking-widest">เหรียญที่ staff จ่าย</h1>
        <NeonButton variant="ghost" onClick={() => refetch()}>รีเฟรช</NeonButton>
      </div>

      <div className="flex gap-2 flex-wrap">
        {[6, 24, 72].map((h) => (
          <button
            key={h}
            onClick={() => setHours(h)}
            className={`px-3 py-1.5 font-mono text-xs ${hours === h ? "neon-border-blue text-neon-blue" : "border border-white/20 text-white/40"}`}
          >
            {h === 6 ? "6 ชม.ล่าสุด" : h === 24 ? "24 ชม.ล่าสุด" : "ทั้งงาน (3 วัน)"}
          </button>
        ))}
      </div>

      {isLoading || !data ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <>
          <RetroCard glow="pink">
            <div className="grid grid-cols-3 gap-3 text-center">
              <Stat label="เหรียญที่จ่ายออก" value={formatCoins(data.summary.coins)} />
              <Stat label="จำนวนครั้ง" value={data.summary.grants.toLocaleString("th-TH")} />
              <Stat label="คนที่ได้รับ" value={data.summary.receivers.toLocaleString("th-TH")} />
            </div>
          </RetroCard>

          {/* ★ ส่วนที่จับคนโกงได้จริง — เอาไว้บนสุด */}
          <RetroCard glow="pink" title="คู่ staff กับผู้รับ ที่จ่ายกันเยอะสุด">
            <p className="text-xs text-white/40 mb-3 leading-relaxed">
              คนทั่วไปรับจาก staff คนหนึ่งไม่กี่ครั้ง ถ้าคู่ไหนโดดขึ้นมาจากคู่อื่นชัดเจน
              แปลว่าอาจเป็นการจ่ายให้คนรู้จัก — กดชื่อไปดูประวัติเต็มได้ที่หน้าประวัติ
            </p>
            {data.pairs.length === 0 ? (
              <p className="text-white/40 text-sm py-2">ยังไม่มีการจ่ายเหรียญในช่วงนี้</p>
            ) : (
              <ul className="space-y-1.5">
                {data.pairs.map((p, i) => {
                  // เทียบกับคู่อันดับหนึ่ง — โดดเกิน 60% ของอันดับหนึ่งถือว่าน่าดู
                  const top = data.pairs[0].coins;
                  const hot = i < 3 && p.coins >= top * 0.6 && p.grants >= 3;
                  return (
                    <li
                      key={`${p.staff}-${p.user_id}`}
                      className={`flex items-center justify-between gap-3 px-3 py-2 text-sm ${
                        hot ? "border border-neon-yellow/40 bg-neon-yellow/5" : "border border-white/10"
                      }`}
                    >
                      <span className="min-w-0 truncate">
                        <span className="text-white/70">{p.staff}</span>
                        <span className="text-white/30 mx-1.5">จ่ายให้</span>
                        <span className="text-white">{p.user}</span>
                      </span>
                      <span className={`font-mono whitespace-nowrap shrink-0 ${hot ? "text-neon-yellow" : "text-white/50"}`}>
                        {formatCoins(p.coins)} · {p.grants} ครั้ง
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </RetroCard>

          <RetroCard glow="blue" title="staff คนไหนจ่ายไปเท่าไหร่">
            {data.by_staff.length === 0 ? (
              <p className="text-white/40 text-sm py-2">ยังไม่มีข้อมูล</p>
            ) : (
              <ul className="space-y-1.5">
                {data.by_staff.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-3 border border-white/10 px-3 py-2">
                    <div className="min-w-0">
                      <p className="text-white text-sm truncate">{s.name}</p>
                      <p className="text-xs text-white/40 font-mono">
                        {formatCoins(s.coins)} เหรียญ · {s.grants} ครั้ง · {s.people} คน
                      </p>
                    </div>
                    {/* บูธที่คนต่อคิวจริงจนชนเพดานรายวัน — ล้างให้ทำงานต่อได้ */}
                    <NeonButton
                      variant="ghost"
                      loading={resetMut.isPending && resetMut.variables === s.id}
                      onClick={() => {
                        if (confirm(`ล้างโควตารายวันของ ${s.name}?\n\nโควตา "ต่อผู้รับ" กับ "ผู้รับต่อวัน" ไม่ถูกล้าง — สองอันนั้นคือด่านกันจ่ายให้พวกพ้อง`))
                          resetMut.mutate(s.id);
                      }}
                    >
                      ล้างโควตา
                    </NeonButton>
                  </li>
                ))}
              </ul>
            )}
          </RetroCard>

          <RetroCard glow="blue" title="ใครรับเหรียญจากบูธไปเยอะสุด">
            {data.by_user.length === 0 ? (
              <p className="text-white/40 text-sm py-2">ยังไม่มีข้อมูล</p>
            ) : (
              <ul className="space-y-1.5">
                {data.by_user.map((u) => (
                  <li key={u.id} className="flex items-center justify-between gap-3 border border-white/10 px-3 py-2 text-sm">
                    <span className="truncate text-white">{u.name}</span>
                    <span className="font-mono text-white/50 whitespace-nowrap shrink-0">
                      {formatCoins(u.coins)} · {u.grants} ครั้ง · จาก {u.from_staff} staff
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </RetroCard>

          <Limits limits={data.limits} />
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-white/40">{label}</p>
      <p className="font-mono text-2xl neon-text-yellow mt-0.5">{value}</p>
    </div>
  );
}

function Limits({ limits }: { limits: GrantSummary["limits"] }) {
  const rows: [string, number, string][] = [
    ["ต่อการสแกน 1 ครั้ง", limits.per_scan, "กันพิมพ์ผิดหลัก (ตั้งใจ 100 พิมพ์ 1000)"],
    ["staff คนหนึ่ง → คนหนึ่ง ต่อวัน", limits.pair_daily, "ด่านกันจ่ายให้เพื่อนโดยตรง"],
    ["คนหนึ่งรับรวมทุกบูธ ต่อวัน", limits.receive_daily, "ด่านกันไล่เก็บจาก staff หลายคน"],
    ["staff คนหนึ่งจ่ายรวม ต่อวัน", limits.staff_daily, "เบรกเกอร์กันเครื่องหลุดมือ"],
  ];
  return (
    <RetroCard glow="purple" title="โควตาที่ตั้งไว้">
      <ul className="space-y-2">
        {rows.map(([label, cap, why]) => (
          <li key={label} className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm text-white/70">{label}</p>
              <p className="text-[11px] text-white/35">{why}</p>
            </div>
            <span className="font-mono text-neon-yellow whitespace-nowrap shrink-0">
              {cap.toLocaleString("th-TH")}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-white/30 mt-3 pt-3 border-t border-white/10 leading-relaxed">
        แก้ตัวเลขได้ที่ไฟล์ .env ของ backend แล้ว restart (ประมาณ 5 วินาที) —
        ถ้าจะหยุดการจ่ายเหรียญทั้งงานทันที ใช้สวิตช์ &quot;จ่ายเหรียญที่บูธ&quot; ที่หน้าฉุกเฉิน
      </p>
    </RetroCard>
  );
}
