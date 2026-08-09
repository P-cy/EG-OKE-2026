"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Quest, type QuestInput } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { toast } from "@/components/Toaster";

// จัดการกิจกรรมบูธ — เพิ่ม/แก้/เปิด-ปิด/ลบ
// staff เอาไปใช้ที่หน้า /scan (โหมดแสตมป์กิจกรรม)
export default function AdminQuestsPage() {
  return (
    <ProtectedRoute roles={["admin"]}>
      <QuestsAdmin />
    </ProtectedRoute>
  );
}

const EMPTY: QuestInput = {
  quest_key: "", title: "", description: "",
  coins: 10, status: "open", max_per_user: 1, sort_order: 0,
};

function QuestsAdmin() {
  const qc = useQueryClient();
  const [form, setForm] = useState<QuestInput>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["admin-quests"],
    queryFn: () => api.adminListQuests(),
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["admin-quests"] });
    qc.invalidateQueries({ queryKey: ["quests"] });
  };

  const createMut = useMutation({
    mutationFn: (body: QuestInput) => api.adminCreateQuest(body),
    onSuccess: () => { toast("เพิ่มกิจกรรมแล้ว", "success"); setForm(EMPTY); refresh(); },
    onError: (e: any) => toast(e.message || "เพิ่มไม่สำเร็จ", "error"),
  });

  const updateMut = useMutation({
    mutationFn: ({ key, body }: { key: string; body: Partial<QuestInput> }) =>
      api.adminUpdateQuest(key, body),
    onSuccess: () => { toast("บันทึกแล้ว", "success"); setEditing(null); refresh(); },
    onError: (e: any) => toast(e.message || "บันทึกไม่สำเร็จ", "error"),
  });

  const deleteMut = useMutation({
    mutationFn: (key: string) => api.adminDeleteQuest(key),
    onSuccess: (res) => { toast(res.message || "ลบแล้ว", res.deleted ? "success" : "warn"); refresh(); },
    onError: (e: any) => toast(e.message || "ลบไม่สำเร็จ", "error"),
  });

  const quests = data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="font-mono text-2xl neon-text-pink tracking-widest">จัดการกิจกรรม</h1>
        <Link href="/scan">
          <NeonButton variant="ghost">ไปหน้าสแกน</NeonButton>
        </Link>
      </div>

      {/* ── เพิ่มกิจกรรมใหม่ ── */}
      <RetroCard glow="pink" title="เพิ่มกิจกรรม">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.quest_key.trim() || !form.title.trim()) {
              toast("ต้องใส่รหัสกับชื่อกิจกรรม", "warn");
              return;
            }
            createMut.mutate(form);
          }}
          className="space-y-3"
        >
          <div className="grid sm:grid-cols-2 gap-3">
            <Field label="รหัสกิจกรรม (a-z 0-9 -)" hint="ใช้อ้างอิงภายใน เปลี่ยนทีหลังไม่ได้">
              <input
                value={form.quest_key}
                onChange={(e) => setForm({ ...form, quest_key: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })}
                className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white font-mono text-sm"
              />
            </Field>
            <Field label="ชื่อกิจกรรม">
              <input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white text-sm"
              />
            </Field>
          </div>

          <Field label="คำอธิบาย (ผู้เข้างานเห็น)">
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={2}
              className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white text-sm"
            />
          </Field>

          <div className="grid grid-cols-3 gap-3">
            <Field label="เหรียญที่ได้">
              <input
                type="number" min={0} max={1000}
                value={form.coins}
                onChange={(e) => setForm({ ...form, coins: Number(e.target.value) })}
                className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white font-mono text-sm"
              />
            </Field>
            <Field label="รับได้กี่ครั้ง/คน">
              <input
                type="number" min={1} max={20}
                value={form.max_per_user}
                onChange={(e) => setForm({ ...form, max_per_user: Number(e.target.value) })}
                className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white font-mono text-sm"
              />
            </Field>
            <Field label="ลำดับ">
              <input
                type="number"
                value={form.sort_order}
                onChange={(e) => setForm({ ...form, sort_order: Number(e.target.value) })}
                className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white font-mono text-sm"
              />
            </Field>
          </div>

          <NeonButton variant="pink" type="submit" loading={createMut.isPending}>
            เพิ่มกิจกรรม
          </NeonButton>
        </form>
      </RetroCard>

      {/* ── รายการ ── */}
      {isLoading ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : quests.length === 0 ? (
        <RetroCard glow="blue">
          <p className="text-center text-white/50 py-4">ยังไม่มีกิจกรรม — เพิ่มด้านบน</p>
        </RetroCard>
      ) : (
        <div className="space-y-2">
          {quests.map((q) => (
            <QuestRow
              key={q.quest_key}
              quest={q}
              editing={editing === q.quest_key}
              onEdit={() => setEditing(editing === q.quest_key ? null : q.quest_key)}
              onSave={(body) => updateMut.mutate({ key: q.quest_key, body })}
              onToggle={() =>
                updateMut.mutate({
                  key: q.quest_key,
                  body: { status: q.status === "open" ? "closed" : "open" },
                })
              }
              onDelete={() => {
                const msg = q.claimed_count
                  ? `มีคนรับไปแล้ว ${q.claimed_count} ครั้ง — จะปิดกิจกรรมแทนการลบ ยืนยัน?`
                  : `ลบ "${q.title}" ถาวร ยืนยัน?`;
                if (confirm(msg)) deleteMut.mutate(q.quest_key);
              }}
              busy={updateMut.isPending || deleteMut.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function QuestRow({
  quest, editing, onEdit, onSave, onToggle, onDelete, busy,
}: {
  quest: Quest;
  editing: boolean;
  onEdit: () => void;
  onSave: (body: Partial<QuestInput>) => void;
  onToggle: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState<Partial<QuestInput>>({
    title: quest.title, description: quest.description,
    coins: quest.coins, max_per_user: quest.max_per_user, sort_order: quest.sort_order,
  });
  const open = quest.status === "open";

  return (
    <RetroCard glow={open ? "blue" : "purple"}>
      {editing ? (
        <div className="space-y-2">
          <input
            value={draft.title ?? ""}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white text-sm"
          />
          <textarea
            value={draft.description ?? ""}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            rows={2}
            className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white text-sm"
          />
          <div className="grid grid-cols-3 gap-2">
            <input
              type="number" value={draft.coins ?? 0}
              onChange={(e) => setDraft({ ...draft, coins: Number(e.target.value) })}
              className="bg-bg-deep neon-border-blue px-2 py-1.5 text-white font-mono text-sm"
            />
            <input
              type="number" value={draft.max_per_user ?? 1}
              onChange={(e) => setDraft({ ...draft, max_per_user: Number(e.target.value) })}
              className="bg-bg-deep neon-border-blue px-2 py-1.5 text-white font-mono text-sm"
            />
            <input
              type="number" value={draft.sort_order ?? 0}
              onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })}
              className="bg-bg-deep neon-border-blue px-2 py-1.5 text-white font-mono text-sm"
            />
          </div>
          <div className="flex gap-2">
            <NeonButton variant="pink" loading={busy} onClick={() => onSave(draft)}>บันทึก</NeonButton>
            <NeonButton variant="ghost" onClick={onEdit}>ยกเลิก</NeonButton>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-white font-medium">{quest.title}</p>
              <span className={`text-[10px] px-1.5 py-0.5 border font-mono ${
                open ? "border-neon-green/40 text-neon-green" : "border-white/20 text-white/30"
              }`}>
                {open ? "เปิด" : "ปิด"}
              </span>
            </div>
            <p className="text-xs text-white/40 font-mono">{quest.quest_key}</p>
            {quest.description && (
              <p className="text-xs text-white/50 mt-0.5 line-clamp-2">{quest.description}</p>
            )}
            <p className="text-xs font-mono text-neon-yellow mt-1">
              +{quest.coins} coin · รับได้ {quest.max_per_user} ครั้ง/คน · มีคนรับแล้ว {quest.claimed_count}
            </p>
          </div>
          <div className="flex gap-2 flex-wrap">
            <NeonButton variant="ghost" onClick={onEdit}>แก้</NeonButton>
            <NeonButton variant={open ? "ghost" : "pink"} loading={busy} onClick={onToggle}>
              {open ? "ปิด" : "เปิด"}
            </NeonButton>
            <NeonButton variant="danger" loading={busy} onClick={onDelete}>ลบ</NeonButton>
          </div>
        </div>
      )}
    </RetroCard>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-white/50 block mb-1">{label}</span>
      {children}
      {hint && <span className="text-[10px] text-white/30 block mt-0.5">{hint}</span>}
    </label>
  );
}
