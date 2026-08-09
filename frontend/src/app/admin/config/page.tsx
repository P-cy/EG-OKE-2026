"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { toast } from "@/components/Toaster";

export default function AdminConfigPage() {
  return (
    <ProtectedRoute roles={["admin"]}>
      <ConfigContent />
    </ProtectedRoute>
  );
}

const FEATURE_LABELS: Record<string, string> = {
  voting: "โหวต",
  wheel: "วงล้อ",
  ig_submission: "ส่ง IG",
  checkin: "เช็คอิน",
  // ★ ปิดอันนี้ = staff จ่ายเหรียญที่บูธไม่ได้ทั้งงาน — ปุ่มฉุกเฉินตอนเครื่องสแกนหลุดมือ
  quests: "จ่ายเหรียญที่บูธ",
};

function ConfigContent() {
  const snap = useQuery({
    queryKey: ["snapshot"],
    queryFn: () => api.getSnapshot(),
    refetchInterval: 3000,
  });

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.adminPatchConfig(body),
    onSuccess: () => toast("ตั้งค่าใหม่มีผลใน 5 วิ", "success"),
    onError: (e: any) => toast(e.message || "ตั้งค่าไม่สำเร็จ", "error"),
  });

  const [annText, setAnnText] = useState("");

  const features = snap.data?.features || {};
  const maintenance = false; // อ่านจาก snapshot ฝั่ง admin แยก endpoint (โครงร่าง)

  return (
    <div className="space-y-6">
      <h1 className="font-mono text-2xl neon-text-pink tracking-widest text-center">ปุ่มฉุกเฉิน</h1>

      <RetroCard glow="pink" title="โหมดระบบ">
        <div className="space-y-3">
          <Toggle
            label="Maintenance (ปิดทั้งเว็บ ขึ้นหน้าแจ้ง)"
            on={maintenance}
            onChange={(v) => patch.mutate({ maintenance_mode: v })}
            danger
          />
          <Toggle
            label="Read-only (อ่านได้ เขียนไม่ได้)"
            on={false}
            onChange={(v) => patch.mutate({ read_only_mode: v })}
            danger
          />
        </div>
      </RetroCard>

      <RetroCard glow="blue" title="เปิด/ปิดฟีเจอร์แต่ละตัว">
        <div className="space-y-3">
          {Object.keys(FEATURE_LABELS).map((key) => (
            <Toggle
              key={key}
              label={FEATURE_LABELS[key]}
              on={!!features[key]}
              onChange={(v) => patch.mutate({ features: { [key]: v } })}
            />
          ))}
        </div>
      </RetroCard>

      <RetroCard glow="purple" title="ประกาศบนหน้าจอ">
        <div className="space-y-3">
          <textarea
            value={annText}
            onChange={(e) => setAnnText(e.target.value)}
            rows={3}
            maxLength={200}
            placeholder="ข้อความที่จะแสดงบนหน้าหลักทุกคน"
            className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white"
          />
          <div className="flex gap-2">
            <NeonButton
              variant="pink"
              loading={patch.isPending}
              onClick={() => patch.mutate({ announcement: { text: annText, level: "info" } })}
            >
              ตั้งประกาศ
            </NeonButton>
            <NeonButton
              variant="ghost"
              onClick={() => { setAnnText(""); patch.mutate({ announcement: { text: "", level: "info" } }); }}
            >
              ล้างประกาศ
            </NeonButton>
          </div>
        </div>
      </RetroCard>

      <RetroCard glow="blue" title="ปุ่มซ่อมระบบ">
        <div className="flex flex-wrap gap-3">
          <NeonButton variant="ghost" onClick={() => toast("ยังไม่เชื่อม backend /admin/reconcile/points", "warn")}>
            fix coin (reconcile)
          </NeonButton>
          <NeonButton variant="ghost" onClick={() => toast("ยังไม่เชื่อม /admin/rebuild/leaderboard", "warn")}>
            สร้าง leaderboard ใหม่
          </NeonButton>
        </div>
      </RetroCard>

      {snap.isLoading && <div className="flex justify-center"><Spinner /></div>}
    </div>
  );
}

function Toggle({
  label, on, onChange, danger,
}: {
  label: string; on: boolean; onChange: (v: boolean) => void; danger?: boolean;
}) {
  return (
    <label className="flex items-center justify-between cursor-pointer">
      <span className={`text-sm ${danger ? "text-neon-pink" : "text-white/80"}`}>{label}</span>
      <button
        type="button"
        onClick={() => onChange(!on)}
        className={`relative w-14 h-7 rounded-full transition-colors ${
          on ? "bg-neon-pink" : "bg-bg-panel2 border border-white/20"
        }`}
        style={on ? { boxShadow: "0 0 10px var(--neon-pink)" } : undefined}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-6 h-6 rounded-full bg-white transition-transform ${
            on ? "translate-x-7" : ""
          }`}
        />
      </button>
    </label>
  );
}
