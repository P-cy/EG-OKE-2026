"use client";

import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api, type AuditLog } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { formatDateTime } from "@/lib/format";

// ป้ายภาษาไทยของ action — ตัวไหนไม่มีในนี้จะโชว์ชื่อดิบ (ไม่ต้องมาแก้โค้ดทุกครั้งที่เพิ่ม action)
const ACTION_LABEL: Record<string, string> = {
  "coins.adjust": "ปรับเหรียญ",
  "coins.reconcile": "ตรวจยอดเหรียญ",
  "ig.approve": "อนุมัติรูป IG",
  "ig.reject": "ปฏิเสธรูป IG",
  "vote_round.open": "เปิดรอบโหวต",
  "vote_round.close": "ปิดรอบโหวต",
  "vote_round.publish": "ประกาศผลโหวต",
  "config.patch": "แก้ค่าระบบ",
  "checkin.manual": "เช็คอินด้วยมือ",
  "checkin.undo": "ยกเลิกเช็คอิน",
  "quest.create": "เพิ่มกิจกรรม",
  "quest.update": "แก้กิจกรรม",
  "quest.delete": "ลบกิจกรรม",
  "quest.close_instead_of_delete": "ปิดกิจกรรม (มีคนรับแล้ว)",
  "leaderboard.rebuild": "สร้างอันดับใหม่",
};

// action ที่ต้องจับตาเป็นพิเศษ — เกี่ยวกับเหรียญหรือการยกเลิกของที่ทำไปแล้ว
const SENSITIVE = new Set(["coins.adjust", "checkin.undo", "quest.delete", "config.patch"]);

export default function AdminAuditPage() {
  return (
    <ProtectedRoute roles={["admin"]}>
      <AuditContent />
    </ProtectedRoute>
  );
}

function AuditContent() {
  const [action, setAction] = useState("");

  const { data: actionsData } = useQuery({
    queryKey: ["audit-actions"],
    queryFn: () => api.adminAuditActions(),
    staleTime: 60_000,
  });

  const { data, isLoading, isFetchingNextPage, hasNextPage, fetchNextPage, refetch, isRefetching } =
    useInfiniteQuery({
      queryKey: ["audit-logs", action],
      queryFn: ({ pageParam }) => api.adminAuditLogs(action || undefined, pageParam as string | undefined),
      initialPageParam: undefined as string | undefined,
      getNextPageParam: (last) => last.next_cursor ?? undefined,
    });

  const items = data?.pages.flatMap((p) => p.items) ?? [];
  // กลุ่มหลักของ action (ก่อนจุด) — ใช้ทำปุ่มกรองแบบกว้าง
  const groups = Array.from(new Set((actionsData?.actions ?? []).map((a) => a.split(".")[0]))).sort();

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="font-mono text-2xl neon-text-pink tracking-widest">ประวัติการใช้งาน Admin</h1>
        <p className="text-white/50 text-sm mt-1">
          ทุก action ของ admin ถูกบันทึกไว้ทั้งหมด — ใช้ตรวจย้อนหลังว่าใครทำอะไรตอนไหน
        </p>
      </div>

      <div className="flex gap-2 flex-wrap justify-center">
        <FilterChip label="ทั้งหมด" active={action === ""} onClick={() => setAction("")} />
        {groups.map((g) => (
          <FilterChip key={g} label={ACTION_LABEL[g] || g} active={action === g} onClick={() => setAction(g)} />
        ))}
        <NeonButton variant="ghost" loading={isRefetching} onClick={() => refetch()}>
          รีเฟรช
        </NeonButton>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : items.length === 0 ? (
        <RetroCard glow="blue">
          <p className="text-center text-white/50">ยังไม่มีบันทึกในหมวดนี้</p>
        </RetroCard>
      ) : (
        <div className="space-y-2">
          {items.map((log) => <LogRow key={log.id} log={log} />)}
          {hasNextPage && (
            <div className="flex justify-center pt-2">
              <NeonButton variant="ghost" loading={isFetchingNextPage} onClick={() => fetchNextPage()}>
                โหลดเพิ่ม
              </NeonButton>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 font-mono text-sm ${
        active ? "neon-border-pink text-neon-pink" : "border border-white/20 text-white/50 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}

function LogRow({ log }: { log: AuditLog }) {
  const [open, setOpen] = useState(false);
  const sensitive = SENSITIVE.has(log.action);
  const hasDetail = log.before != null || log.after != null;

  return (
    <div className={`retro-panel rounded p-3 border ${sensitive ? "border-neon-pink/40" : "border-white/10"}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <p className={`font-mono text-sm ${sensitive ? "neon-text-pink" : "text-white/85"}`}>
            {ACTION_LABEL[log.action] || log.action}
            <span className="text-white/25 text-xs ml-2">{log.action}</span>
          </p>
          <p className="text-xs text-white/50 mt-0.5">
            โดย {log.actor.display_name || log.actor.email || log.actor.id}
          </p>
          {log.target?.id && (
            <p className="text-xs text-white/35 font-mono break-all">
              เป้าหมาย: {log.target.type}/{log.target.id}
            </p>
          )}
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs text-white/40 font-mono">{formatDateTime(log.created_at)}</p>
          {hasDetail && (
            <button onClick={() => setOpen((v) => !v)} className="text-xs text-neon-blue mt-1">
              {open ? "ซ่อนรายละเอียด" : "ดูรายละเอียด"}
            </button>
          )}
        </div>
      </div>

      {open && hasDetail && (
        <div className="mt-3 pt-3 border-t border-white/10 grid sm:grid-cols-2 gap-3">
          <DetailBox title="ก่อน" value={log.before} />
          <DetailBox title="หลัง" value={log.after} />
        </div>
      )}
    </div>
  );
}

function DetailBox({ title, value }: { title: string; value: unknown }) {
  return (
    <div>
      <p className="text-[10px] text-white/40 font-mono tracking-widest mb-1">{title}</p>
      <pre className="text-xs text-white/70 bg-black/40 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
        {value == null ? "—" : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
