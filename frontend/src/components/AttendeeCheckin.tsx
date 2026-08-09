"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type AttendeeRow } from "@/lib/api";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { toast } from "@/components/Toaster";
import { formatCoins, formatTime } from "@/lib/format";

// เช็คชื่อจากรายชื่อ — ทางถอยตอนบัตร QR พัง/หาย/สแกนไม่ติด
//
// ★ ใช้ร่วมกัน 2 หน้า: /admin/attendees กับ /staff/attendees
//   ต่างกันแค่ปุ่มยกเลิกเช็คอิน (admin เท่านั้น) กับ endpoint ที่ยิง
//   ถ้าเขียนแยกสองไฟล์ พอแก้บั๊กที่หนึ่งอีกที่จะค้างเวอร์ชันเก่าโดยไม่มีใครรู้
//
// ★ "วันที่จะเช็ค" แยกจาก "วันที่ใช้กรอง" — ของเดิมใช้ตัวเดียวกัน พอเลือก "ทุกวัน"
//   ปุ่มจะเช็คเข้าวัน 1 เงียบๆ ซึ่งเป็นข้อมูลผิดที่แก้ยาก
export function AttendeeCheckin({ mode }: { mode: "admin" | "staff" }) {
  const qc = useQueryClient();
  const isAdmin = mode === "admin";
  const [q, setQ] = useState("");
  const [filterDay, setFilterDay] = useState<number | undefined>(undefined);
  const [status, setStatus] = useState<string | undefined>(undefined);
  const [targetDay, setTargetDay] = useState(() => {
    if (typeof window === "undefined") return 1;
    const d = Number(localStorage.getItem("scan:event_day"));
    return d >= 1 && d <= 3 ? d : 1;   // ใช้วันเดียวกับเครื่องสแกนเป็นค่าเริ่มต้น
  });

  const queryKey = [`${mode}-attendees`, q, filterDay, status];
  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () =>
      isAdmin
        ? api.adminAttendees(q, filterDay, status)
        : api.staffAttendees(q, filterDay, status),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: [`${mode}-attendees`] });

  const checkinMut = useMutation({
    mutationFn: ({ user_id, event_day }: { user_id: string; event_day: number }) =>
      isAdmin
        ? api.adminManualCheckin(user_id, event_day)
        : api.staffManualCheckin(user_id, event_day),
    onSuccess: (res) => {
      toast(res.message || `เช็คชื่อแล้ว (${res.result})`, res.result === "ok" ? "success" : "warn");
      invalidate();
    },
    onError: (e: any) => toast(e.message || "เช็คชื่อไม่สำเร็จ", "error"),
  });

  const undoMut = useMutation({
    mutationFn: ({ user_id, event_day }: { user_id: string; event_day: number }) =>
      api.adminUndoCheckin(user_id, event_day),
    onSuccess: () => {
      toast("ยกเลิกเช็คอินแล้ว", "success");
      invalidate();
    },
    onError: (e: any) => toast(e.message || "ยกเลิกไม่สำเร็จ", "error"),
  });

  return (
    <div className="space-y-5">
      <h1 className="font-mono text-2xl neon-text-pink tracking-widest text-center">เช็คชื่อด้วยมือ</h1>

      {/* ★ หน้านี้ไม่มีกล้อง — ต้องบอกให้ชัดว่ากล้องอยู่ไหน
          ไม่งั้นคนเปิดมาแล้วนึกว่ากล้องหายไปจากระบบ */}
      <Link href="/scan" className="block">
        <div className="border border-neon-green/40 bg-neon-green/5 px-4 py-3 flex items-center justify-between gap-3 hover:bg-neon-green/10 transition-colors">
          <div className="min-w-0">
            <p className="text-neon-green font-mono text-sm">ต้องการสแกน QR ด้วยกล้อง?</p>
            <p className="text-xs text-white/50 mt-0.5">หน้านี้ใช้ค้นรายชื่อด้วยมือเท่านั้น — กล้องอยู่ที่หน้าสแกน</p>
          </div>
          <span className="text-neon-green font-mono text-sm whitespace-nowrap shrink-0">เปิดกล้อง</span>
        </div>
      </Link>

      {/* ★ วันที่จะเช็คเข้า — ต้องชัดที่สุดในหน้านี้ */}
      <RetroCard glow="pink" title="กำลังเช็คชื่อเข้าวันที่">
        <div className="flex gap-2">
          {[1, 2, 3].map((d) => (
            <button
              key={d}
              onClick={() => setTargetDay(d)}
              className={`flex-1 px-4 py-3 font-mono text-lg ${targetDay === d ? "neon-border-pink text-neon-pink bg-neon-pink/10" : "border border-white/20 text-white/50"}`}
            >
              วันที่ {d}
            </button>
          ))}
        </div>
      </RetroCard>

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="ค้นหา email / ชื่อ / รหัสนักศึกษา"
        className="w-full bg-bg-deep neon-border-blue px-4 py-3 text-white"
      />

      {/* กรองรายชื่อที่แสดง */}
      <div className="flex flex-wrap gap-2 justify-center">
        {[undefined, 1, 2, 3].map((d) => (
          <button
            key={String(d)}
            onClick={() => setFilterDay(d)}
            className={`px-3 py-1.5 font-mono text-xs ${filterDay === d ? "neon-border-blue text-neon-blue" : "border border-white/20 text-white/40"}`}
          >
            {d === undefined ? "แสดงทุกคน" : `เข้าแล้ววัน ${d}`}
          </button>
        ))}
        {[undefined, "checked", "unchecked"].map((s) => (
          <button
            key={s || "all"}
            onClick={() => setStatus(s)}
            className={`px-3 py-1.5 text-xs ${status === s ? "neon-border-blue text-neon-blue" : "border border-white/20 text-white/40"}`}
          >
            {s === undefined ? "ทุกสถานะ" : s === "checked" ? "เคยเข้างาน" : "ยังไม่เคยเข้า"}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <div className="space-y-2">
          {data?.items.length === 0 && (
            <p className="text-center text-white/40 py-8">
              ไม่พบผู้เข้างาน — ลองพิมพ์ชื่อหรือรหัสนักศึกษาเพื่อค้นหา
            </p>
          )}
          {data?.items.map((a) => (
            <AttendeeCard
              key={a.id}
              row={a}
              targetDay={targetDay}
              canUndo={isAdmin}
              onCheckin={() => checkinMut.mutate({ user_id: a.id, event_day: targetDay })}
              onUndo={(d) => undoMut.mutate({ user_id: a.id, event_day: d })}
              loading={
                (checkinMut.isPending && checkinMut.variables?.user_id === a.id) ||
                (undoMut.isPending && undoMut.variables?.user_id === a.id)
              }
            />
          ))}
          {data?.next_cursor && (
            <p className="text-center text-white/30 text-xs pt-2">
              แสดง {data.items.length} คนแรก — พิมพ์ค้นหาเพื่อดูคนที่เหลือ
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function AttendeeCard({
  row, targetDay, canUndo, onCheckin, onUndo, loading,
}: {
  row: AttendeeRow;
  targetDay: number;
  canUndo: boolean;
  onCheckin: () => void;
  onUndo: (day: number) => void;
  loading?: boolean;
}) {
  const already = row.checked_in_days.includes(targetDay);

  return (
    <RetroCard glow="blue">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-white font-medium truncate">{row.display_name || "-"}</p>
          {/* ชื่อจริงจาก Google — ใช้เทียบกับบัตรตอนคนไม่มีรหัสนักศึกษา */}
          {row.full_name && row.full_name !== row.display_name && (
            <p className="text-xs text-white/50 truncate">{row.full_name}</p>
          )}
          <p className="text-xs text-white/40 truncate">
            {row.email}{row.student_id ? ` · ${row.student_id}` : ""}
          </p>
          <p className="text-xs font-mono text-neon-yellow">
            {row.ticket_code || "ยังไม่มีบัตร"} · {formatCoins(row.coins_balance)} coin
          </p>
          <div className="flex gap-1 mt-1 items-center">
            {[1, 2, 3].map((d) => {
              const checked = row.checked_in_days.includes(d);
              // กดที่วันที่เขียวเพื่อยกเลิก — ทางแก้เดียวเมื่อเช็คผิดวัน (admin เท่านั้น)
              const undoable = checked && canUndo;
              return (
                <button
                  key={d}
                  onClick={() => undoable && onUndo(d)}
                  disabled={!undoable || loading}
                  title={undoable ? `กดเพื่อยกเลิกเช็คอินวัน ${d}` : ""}
                  className={`text-xs px-1.5 py-0.5 border ${
                    checked
                      ? undoable
                        ? "border-neon-green/40 text-neon-green hover:border-red-500 hover:text-red-400 cursor-pointer"
                        : "border-neon-green/40 text-neon-green cursor-default"
                      : "border-white/20 text-white/30 cursor-default"
                  }`}
                >
                  วัน{d}
                </button>
              );
            })}
            {row.last_checked_in_at && (
              <span className="text-[10px] text-white/30 ml-1">
                ล่าสุด {formatTime(row.last_checked_in_at)}
              </span>
            )}
          </div>
        </div>

        {row.ticket_code ? (
          <NeonButton
            variant={already ? "ghost" : "pink"}
            loading={loading}
            disabled={already}
            onClick={onCheckin}
          >
            {already ? `เข้าวัน${targetDay} แล้ว` : `เช็คเข้าวัน ${targetDay}`}
          </NeonButton>
        ) : (
          <span className="text-xs text-red-400">ยังไม่มีบัตร</span>
        )}
      </div>
    </RetroCard>
  );
}
