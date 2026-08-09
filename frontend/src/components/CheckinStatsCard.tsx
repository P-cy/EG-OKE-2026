"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { RetroCard } from "@/components/RetroCard";
import { formatTime } from "@/lib/format";

// อัปเดตทุก 5 วิ — ข้อมูลมาจาก Redis ล้วน ไม่แตะ Mongo
// และ nginx cache ให้อีก 1 วิ ต่อให้ staff เปิดค้างไว้พร้อมกันทั้งทีม
// backend ก็เห็นแค่ประมาณ 1 request ต่อวินาที
const REFRESH_MS = 5000;

/** สถิติเช็คอินสด — ให้ staff ที่ยืนอยู่หน้าประตูรู้ว่าตอนนี้คนไหลเข้าเร็วแค่ไหน
 *  และประตูไหนแน่นกว่ากัน จะได้ย้ายคนไปช่วยได้ทัน
 */
export function CheckinStatsCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["checkin-stats"],
    queryFn: () => api.getCheckinStats(),
    refetchInterval: REFRESH_MS,
    // ยังโชว์ตัวเลขเดิมระหว่างรอบใหม่กำลังโหลด — ไม่งั้นเลขจะกระพริบทุก 5 วิ
    placeholderData: (prev) => prev,
  });

  if (isLoading) {
    return (
      <RetroCard glow="green" title="เช็คอินวันนี้">
        <p className="text-white/40 text-sm">กำลังโหลด...</p>
      </RetroCard>
    );
  }

  // ★ ล้มแล้วไม่ต้องโชว์อะไรเลย — การ์ดนี้เป็นข้อมูลประกอบ ไม่ใช่เครื่องมือทำงาน
  //   ถ้าขึ้นกล่องแดงค้างไว้ staff จะนึกว่าระบบเช็คอินพัง ทั้งที่การสแกนยังใช้ได้ปกติ
  if (isError || !data) return null;

  const gates = Object.entries(data.gates).sort((a, b) => b[1] - a[1]);

  return (
    <RetroCard glow="green" title="เช็คอินวันนี้">
      <div className="flex items-end gap-6 flex-wrap">
        <div>
          <p className="font-mono text-4xl text-neon-green leading-none">
            {data.today.toLocaleString("th-TH")}
          </p>
          <p className="text-xs text-white/40 mt-1">คนที่เช็คอินแล้ววันนี้</p>
        </div>
        <div>
          <p className="font-mono text-2xl text-neon-yellow leading-none">
            {data.rate_per_min}
          </p>
          <p className="text-xs text-white/40 mt-1">คน/นาที (1 นาทีล่าสุด)</p>
        </div>
      </div>

      {gates.length > 0 && (
        <div className="mt-4 pt-3 border-t border-white/10">
          <p className="text-xs text-white/40 mb-2">แยกตามประตู</p>
          <div className="flex gap-2 flex-wrap">
            {gates.map(([gate, n]) => (
              <span
                key={gate}
                className="font-mono text-xs px-2 py-1 border border-neon-green/30 text-neon-green"
              >
                {gate} · {n.toLocaleString("th-TH")}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.recent.length > 0 && (
        <div className="mt-4 pt-3 border-t border-white/10">
          <p className="text-xs text-white/40 mb-2">คนล่าสุด</p>
          <ul className="space-y-1">
            {data.recent.slice(0, 6).map((r, i) => (
              // ★ key ใช้ at+index ไม่ใช้ชื่อ — ชื่อเล่นซ้ำกันได้ง่ายมาก
              //   ("ปอ" สองคนติดกัน React จะบ่นเรื่อง duplicate key)
              <li key={`${r.at}-${i}`} className="flex justify-between gap-3 text-sm">
                <span className="text-white/80 truncate">{r.display_name}</span>
                <span className="font-mono text-xs text-white/35 shrink-0">
                  {r.gate} · {formatTime(r.at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </RetroCard>
  );
}
