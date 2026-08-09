"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type AdminIGRow } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { toast } from "@/components/Toaster";
import { igLabel, formatDateTime } from "@/lib/format";

export default function AdminIGPage() {
  return (
    <ProtectedRoute roles={["admin"]}>
      <IGQueue />
    </ProtectedRoute>
  );
}

function IGQueue() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("pending");

  const { data, isLoading } = useQuery({
    queryKey: ["admin-ig-queue", filter],
    queryFn: () => api.adminIGQueue(filter),
    // ★ 15 วิ ไม่ใช่ 5 — คิวนี้แนบ base64 ของทุกใบมาด้วย (รูปที่ยังไม่อนุมัติเปิด public ไม่ได้)
    //   ยิงทุก 5 วิ = ดึงรูปทั้งหน้าใหม่ 12 ครั้ง/นาที ตลอดที่เปิดหน้าไว้
    refetchInterval: 15000,
  });

  const approveMut = useMutation({
    mutationFn: (id: string) => api.adminIGApprove(id),
    onSuccess: () => {
      toast("อนุมัติแล้ว จะขึ้นจอตามคิว", "success");
      qc.invalidateQueries({ queryKey: ["admin-ig-queue"] });
      qc.invalidateQueries({ queryKey: ["admin-dashboard"] });
    },
    onError: (e: any) => toast(e.message || "อนุมัติไม่สำเร็จ", "error"),
  });

  const rejectMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => api.adminIGReject(id, reason),
    onSuccess: (res) => {
      toast(`ปฏิเสธแล้ว — คืน ${res.coins_refunded ?? 0} coin ให้ผู้ส่ง`, "info");
      qc.invalidateQueries({ queryKey: ["admin-ig-queue"] });
      qc.invalidateQueries({ queryKey: ["admin-dashboard"] });
    },
    onError: (e: any) => toast(e.message || "ปฏิเสธไม่สำเร็จ", "error"),
  });

  // ล้างคิวจอ — ใช้ตอนขึ้นวันใหม่ หรือล้างข้อมูลทดสอบก่อนเปิดงานจริง
  // ★ ถามยืนยันก่อน เพราะกดแล้วย้อนไม่ได้จากหน้าเว็บ (ต้องไปแก้ใน DB)
  const clearWallMut = useMutation({
    mutationFn: () => api.adminClearIGWall(),
    onSuccess: (res) => {
      toast(`ล้างคิวจอแล้ว ${res.cleared} โพสต์ — โพสต์ยังอยู่ในระบบ ไม่ได้ลบ`, "success");
      qc.invalidateQueries({ queryKey: ["admin-ig-queue"] });
    },
    onError: (e: any) => toast(e.message || "ล้างคิวไม่สำเร็จ", "error"),
  });

  return (
    <div className="space-y-6">
      <h1 className="font-mono text-2xl neon-text-pink tracking-widest text-center">คิวตรวจ Instagram</h1>

      <RetroCard glow="purple" title="คิวจอใหญ่">
        <p className="text-sm text-white/60 mb-3">
          โพสต์ที่อนุมัติแล้วจะเข้าคิวขึ้นจอ ใบละ 45 วินาที{" "}
          <span className="text-white/80">ขึ้นครบเวลาแล้วตัดออกจากคิวถาวร ไม่วนซ้ำ</span>
        </p>
        <NeonButton
          variant="ghost"
          loading={clearWallMut.isPending}
          onClick={() => {
            if (confirm("ล้างคิวจอทั้งหมด?\n\nโพสต์ที่ค้างอยู่จะไม่ขึ้นจออีก (ไม่ได้ลบโพสต์ ไม่ได้คืนเหรียญ)\nกดแล้วย้อนกลับจากหน้าเว็บไม่ได้")) {
              clearWallMut.mutate();
            }
          }}
        >
          ล้างคิวจอ
        </NeonButton>
        <p className="text-[11px] text-white/30 mt-2">
          ใช้ตอนขึ้นวันใหม่ หรือล้างข้อมูลทดสอบก่อนเปิดงาน
        </p>
      </RetroCard>

      <div className="flex gap-2 justify-center">
        {["pending", "approved", "rejected"].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 font-mono text-sm ${filter === f ? "neon-border-pink text-neon-pink" : "border border-white/20 text-white/50"}`}
          >
            {labelFilter(f)}
            {f === "pending" && data?.total_pending ? ` (${data.total_pending})` : ""}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : data?.items?.length ? (
        <div className="space-y-4">
          {data.items.map((item) => (
            <IGCard
              key={item.id}
              item={item}
              onApprove={() => approveMut.mutate(item.id)}
              onReject={(reason) => rejectMut.mutate({ id: item.id, reason })}
              busy={approveMut.isPending || rejectMut.isPending}
            />
          ))}
        </div>
      ) : (
        <RetroCard glow="blue">
          <p className="text-center text-white/50">ไม่มีรายการในสถานะนี้</p>
        </RetroCard>
      )}
    </div>
  );
}

function IGCard({
  item, onApprove, onReject, busy,
}: {
  item: AdminIGRow;
  onApprove: () => void;
  onReject: (reason: string) => void;
  busy: boolean;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [zoom, setZoom] = useState(false);

  // ชื่อ IG ที่จะขึ้นจอ = ของใบนี้ ไม่ใช่ handle ในโปรไฟล์
  const handle = item.instagram_handle || item.user.instagram_handle || "";

  return (
    <RetroCard glow="pink">
      <div className="flex flex-col sm:flex-row gap-4">
        {/* ── รูป: เล็กลง กว้างคงที่ ให้เห็นหลายใบพร้อมกัน ── */}
        <div className="shrink-0">
          {item.image_data ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={item.image_data}
              alt=""
              onClick={() => setZoom(true)}
              className="w-40 h-40 sm:w-44 sm:h-44 object-cover rounded neon-border-blue cursor-zoom-in"
            />
          ) : (
            <div className="w-40 h-40 sm:w-44 sm:h-44 rounded border border-white/20 flex items-center justify-center text-center text-xs text-white/30 px-2">
              ไม่มีรูป
            </div>
          )}
          {item.image_data && (
            <p className="text-[10px] text-white/30 text-center mt-1">คลิกเพื่อดูเต็ม</p>
          )}
        </div>

        {/* ── สิ่งที่จะขึ้นจอ: ชื่อ IG + แคปชัน ── */}
        <div className="flex-1 min-w-0 space-y-3">
          <div className="retro-panel neon-border-blue rounded p-3 space-y-2">
            <p className="text-[10px] text-white/40 font-mono tracking-widest">จะขึ้นจอแบบนี้</p>
            <p className="font-mono text-xl neon-text-blue break-all">
              {handle ? igLabel(handle) : <span className="text-red-400 text-sm">ไม่ระบุชื่อ IG</span>}
            </p>
            {item.caption ? (
              <p className="text-white/80 text-sm whitespace-pre-wrap break-words">{item.caption}</p>
            ) : (
              <p className="text-white/25 text-sm italic">ไม่มีแคปชัน</p>
            )}
          </div>

          <div className="text-xs space-y-0.5">
            <p className="text-white/50">ผู้ส่ง: {item.user.display_name || "?"}</p>
            <p className="text-white/35">ส่งเมื่อ: {formatDateTime(item.submitted_at)}</p>
            {item.auto_flags?.length > 0 && (
              <p className="text-neon-pink">ธงอัตโนมัติ: {item.auto_flags.join(", ")}</p>
            )}
          </div>
        </div>

        {item.status === "pending" && (
          <div className="sm:w-44 flex flex-col gap-2 justify-center shrink-0">
            {rejecting ? (
              <div className="space-y-2">
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={3}
                  placeholder="เหตุผลที่ปฏิเสธ"
                  className="w-full bg-bg-deep neon-border-pink px-2 py-1 text-sm text-white"
                />
                <div className="flex gap-2">
                  <NeonButton variant="danger" onClick={() => { if (reason.trim()) { onReject(reason.trim()); setRejecting(false); } }}>
                    ยืนยันปฏิเสธ
                  </NeonButton>
                  <NeonButton variant="ghost" onClick={() => setRejecting(false)}>ยกเลิก</NeonButton>
                </div>
              </div>
            ) : (
              <>
                <NeonButton variant="pink" loading={busy} onClick={onApprove}>
                  อนุมัติ ขึ้นจอ
                </NeonButton>
                <NeonButton variant="danger" loading={busy} onClick={() => setRejecting(true)}>
                  ปฏิเสธ
                </NeonButton>
              </>
            )}
          </div>
        )}
      </div>

      {/* ดูรูปเต็มเมื่อจำเป็น — ไม่ต้องให้รูปใหญ่กินพื้นที่ตลอดเวลา */}
      {zoom && item.image_data && (
        <div
          onClick={() => setZoom(false)}
          className="fixed inset-0 z-[90] bg-black/90 flex items-center justify-center p-4 cursor-zoom-out"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={item.image_data} alt="" className="max-w-full max-h-full object-contain" />
        </div>
      )}
    </RetroCard>
  );
}

function labelFilter(f: string): string {
  return { pending: "รอตรวจ", approved: "อนุมัติแล้ว", rejected: "ปฏิเสธแล้ว" }[f] || f;
}
