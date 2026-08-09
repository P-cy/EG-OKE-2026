"use client";

import type { IGSubmission } from "@/lib/api";
import { igLabel, relativeTime } from "@/lib/format";

const STATUS_COLOR: Record<string, string> = {
  pending: "text-neon-yellow",
  approved: "text-neon-green",
  rejected: "text-red-400",
  flagged: "text-neon-pink",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "รอตรวจ",
  approved: "อนุมัติแล้ว",
  rejected: "ปฏิเสธ",
  flagged: "ตั้งข้อสังเกต",
};

export function IGStatusBadge({ status }: { status: string }) {
  return (
    <span className={`text-sm font-mono shrink-0 ${STATUS_COLOR[status] || "text-white/50"}`}>
      {STATUS_LABEL[status] || status}
    </span>
  );
}

/** หนึ่งแถวในกล่อง "สถานะคำขอของคุณ"
 *
 * ★ ทุกอย่างที่แสดงต้องมาจาก `sub` เท่านั้น
 *   ของเดิมหน้า /ig ดึงชื่อ IG จาก state ของช่องกรอกที่ยังพิมพ์ค้างอยู่
 *   → ทุกแถวขึ้นชื่อเดียวกันหมด และเปลี่ยนตามที่กำลังพิมพ์
 */
export function IGSubmissionRow({ sub, refundCoins }: { sub: IGSubmission; refundCoins?: number }) {
  return (
    <div className="border-b border-white/10 pb-3 last:border-0 last:pb-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-white/80 font-mono break-all">
            {sub.instagram_handle ? igLabel(sub.instagram_handle) : "(ไม่ระบุชื่อ IG)"}
          </p>
          {sub.caption && <p className="text-xs text-white/50 mt-0.5 break-words">{sub.caption}</p>}
          <p className="text-xs text-white/40 mt-0.5">ส่งเมื่อ {relativeTime(sub.submitted_at)}</p>
        </div>
        <IGStatusBadge status={sub.status} />
      </div>
      {sub.status === "rejected" && (
        <p className="text-xs text-red-400/80 mt-1">
          เหตุผล: {sub.reject_reason || "ไม่ระบุ"}
          {refundCoins ? ` — คืน ${refundCoins} coin ให้แล้ว` : ""}
        </p>
      )}
    </div>
  );
}
