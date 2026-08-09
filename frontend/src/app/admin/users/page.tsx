"use client";

import { useEffect, useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { Spinner } from "@/components/Spinner";
import { toast } from "@/components/Toaster";
import { formatCoins } from "@/lib/format";

export default function AdminUsersPage() {
  return (
    <ProtectedRoute roles={["admin"]}>
      <UsersContent />
    </ProtectedRoute>
  );
}

function UsersContent() {
  const qc = useQueryClient();
  const { user: me, refreshUser } = useAuth();
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  // ★ หน่วง 300ms ก่อนยิง — ของเดิมยิง query ทุกตัวอักษรที่พิมพ์
  //   ค้นหาเป็น regex บน users 5,000 แถว = ยิงรัวสิบกว่ารอบต่อคำค้นหนึ่งคำ
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  // ★ ของเดิมทิ้ง next_cursor ที่ backend ส่งมา → เห็นได้แค่ 50 คนแรกตลอดกาล
  //   งานนี้มีผู้เข้าร่วม ~5,000 คน แปลว่าคนที่ 51 เป็นต้นไปเข้าไม่ถึงเลย
  const { data, isLoading, isFetchingNextPage, hasNextPage, fetchNextPage } = useInfiniteQuery({
    queryKey: ["admin-users", debouncedQ],
    queryFn: ({ pageParam }) => api.adminUsers(debouncedQ, pageParam as string | undefined),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const users = data?.pages.flatMap((p) => p.users) ?? [];

  // ★ ตั้งสิทธิ์ — role ฝังอยู่ใน access token (อายุ 15 นาที) ไม่ได้อ่านจาก DB ทุก request
  //   คนที่เพิ่งได้ role จึงยังใช้ไม่ได้จนกว่า token จะรอบใหม่ backend ส่ง takes_effect
  //   กลับมาบอก ต้องเอามาโชว์ ไม่งั้น admin จะงงว่ากดแล้วทำไมคนนั้นยังเข้าไม่ได้
  const rolesMut = useMutation({
    mutationFn: ({ id, roles }: { id: string; roles: string[] }) => api.adminSetRoles(id, roles),
    onSuccess: (res) => {
      toast(`สิทธิ์ใหม่: ${res.roles.join(", ")} — ${res.takes_effect}`, "success");
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (e: any) => toast(e.message || "ตั้งสิทธิ์ไม่สำเร็จ", "error"),
  });

  const adjustMut = useMutation({
    mutationFn: ({ id, amount, note }: { id: string; amount: number; note: string }) =>
      api.adminAdjustCoins(id, amount, note),
    onSuccess: (res, vars) => {
      toast(`adjust coinแล้ว คงเหลือ ${res.new_balance}`, "success");
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      // ★ ถ้าเติมให้ตัวเอง → อัปเดต auth store ทันที ไม่งั้นหน้าอื่นยังเห็นยอดเก่า
      if (me && me.id === vars.id) {
        refreshUser();
      }
      setSelected(null); setAmount(""); setNote("");
    },
    onError: (e: any) => {
      // แสดงรายละเอียด validation error ให้ staff เห็นชัด (เช่น note สั้นเกิน)
      const det = e.details;
      if (det && Array.isArray(det)) {
        const msg = det.map((d: any) => `${d.loc?.slice(-1)[0] || "field"}: ${d.msg}`).join(", ");
        toast(msg || e.message || "ปรับไม่สำเร็จ", "error");
      } else {
        toast(e.message || "ปรับไม่สำเร็จ", "error");
      }
    },
  });

  return (
    <div className="space-y-6">
      <h1 className="font-mono text-2xl neon-text-pink tracking-widest text-center">จัดการผู้ใช้</h1>

      <div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="ค้นหาด้วย email / ชื่อ / รหัสนักศึกษา"
          className="w-full bg-bg-deep neon-border-blue px-4 py-3 text-white"
        />
        <p className="text-xs text-white/30 mt-1">
          แสดง {users.length} คน{hasNextPage ? " (ยังมีต่อ)" : ""}
          {q !== debouncedQ ? " · กำลังพิมพ์..." : ""}
        </p>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : users.length === 0 ? (
        <RetroCard glow="blue">
          <p className="text-center text-white/50">ไม่พบผู้ใช้ที่ตรงกับคำค้น</p>
        </RetroCard>
      ) : (
        <div className="space-y-2">
          {users.map((u) => (
            <RetroCard key={u.id} glow="blue">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <p className="text-white font-medium">{u.display_name || "-"}</p>
                  <p className="text-xs text-white/40">{u.email} {u.student_id ? `· ${u.student_id}` : ""}</p>
                  <p className="text-xs text-neon-yellow font-mono">{formatCoins(u.coins_balance)} coin</p>
                  <div className="flex gap-1 mt-1 flex-wrap">
                    {u.roles.map((r) => (
                      <span key={r} className="text-xs px-1.5 py-0.5 border border-white/20 text-white/50">{r}</span>
                    ))}
                    <span className={`text-xs px-1.5 py-0.5 border ${u.status === "active" ? "border-neon-green/40 text-neon-green" : "border-red-500/40 text-red-400"}`}>
                      {u.status}
                    </span>
                  </div>

                  {/* ── ตั้งสิทธิ์ ── */}
                  <RoleControls
                    roles={u.roles}
                    isSelf={me?.id === u.id}
                    busy={rolesMut.isPending && rolesMut.variables?.id === u.id}
                    onSet={(roles) => rolesMut.mutate({ id: u.id, roles })}
                  />
                </div>
                <NeonButton variant="ghost" onClick={() => { setSelected(selected === u.id ? null : u.id); setAmount(""); setNote(""); }}>
                  {selected === u.id ? "ปิด" : "adjust coin"}
                </NeonButton>
              </div>

              {selected === u.id && (
                <div className="mt-4 pt-4 border-t border-white/10 space-y-3">
                  <div className="flex gap-2 items-center">
                    <span className="text-sm text-white/60">จำนวน</span>
                    <input
                      type="number"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      className="bg-bg-deep neon-border-blue px-3 py-2 text-white w-32"
                    />
                    <span className="text-xs text-white/40">ลบได้ (ใส่ค่าติดลบ)</span>
                  </div>
                  <input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="เหตุผล — เก็บใน audit log"
                    maxLength={200}
                    className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white"
                  />
                  <NeonButton
                    variant="pink"
                    loading={adjustMut.isPending}
                    onClick={() => {
                      if (!note.trim()) return toast("ยังไม่ได้ใส่เหตุผล", "warn");
                      const n = Number(amount);
                      if (!amount.trim() || Number.isNaN(n))
                        return toast("ใส่จำนวน coin ก่อน", "warn");
                      if (!Number.isInteger(n)) return toast("จำนวน coin ต้องเป็นจำนวนเต็ม", "warn");
                      if (n === 0) return toast("จำนวน coin ต้องไม่เป็น 0", "warn");
                      adjustMut.mutate({ id: u.id, amount: n, note: note.trim() });
                    }}
                  >
                    ยืนยันadjust coin
                  </NeonButton>
                </div>
              )}
            </RetroCard>
          ))}

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

/** เลือกสิทธิ์ให้ผู้ใช้ — 3 ระดับ กดได้ทีละอัน
 *
 * ★ ส่งเป็นชุดเต็มเสมอ ไม่ใช่ "เพิ่ม/ลบทีละ role" — กดซ้ำแล้วผลเหมือนเดิม
 *   ถ้าเป็นแบบ toggle แล้วเน็ตช้า กดสองที = สลับไปมา ไม่มีใครรู้ว่าลงเอยยังไง
 */
function RoleControls({ roles, isSelf, busy, onSet }: {
  roles: string[];
  isSelf: boolean;
  busy: boolean;
  onSet: (roles: string[]) => void;
}) {
  const superadmin = roles.includes("superadmin");
  const level = roles.includes("admin") ? "admin" : roles.includes("staff") ? "staff" : "participant";

  const LEVELS: { key: string; label: string; roles: string[]; hint: string }[] = [
    { key: "participant", label: "ผู้เข้างาน", roles: [], hint: "ใช้เว็บได้อย่างเดียว" },
    { key: "staff", label: "Staff", roles: ["staff"], hint: "สแกนเช็คอิน + แจกเหรียญที่บูธ" },
    { key: "admin", label: "Admin", roles: ["admin"], hint: "ทุกอย่าง" },
  ];

  // superadmin ตั้งผ่านหน้าเว็บไม่ได้ (แก้ใน DB เท่านั้น) — ไม่ต้องโชว์ปุ่มให้กดพลาด
  if (superadmin) {
    return <p className="text-[10px] text-white/30 mt-1.5 font-mono">superadmin — เปลี่ยนสิทธิ์ได้ใน DB เท่านั้น</p>;
  }

  return (
    <div className="mt-2">
      <div className="flex gap-1 flex-wrap">
        {LEVELS.map((l) => {
          const active = level === l.key;
          // ★ ถอด admin ของตัวเองไม่ได้ — ล็อกตัวเองออกกลางงานแล้วไม่มีใครแก้ให้
          //   backend กันไว้อีกชั้น (CANNOT_DEMOTE_SELF) ตรงนี้แค่ไม่ให้กดตั้งแต่แรก
          const blocked = isSelf && level === "admin" && l.key !== "admin";
          return (
            <button
              key={l.key}
              disabled={active || busy || blocked}
              title={blocked ? "ถอดสิทธิ์ admin ของตัวเองไม่ได้" : l.hint}
              onClick={() => onSet(l.roles)}
              className={`text-[11px] px-2 py-1 border font-mono transition-colors ${
                active
                  ? "border-neon-pink text-neon-pink bg-neon-pink/10"
                  : blocked
                    ? "border-white/10 text-white/20 cursor-not-allowed"
                    : "border-white/20 text-white/40 hover:text-white hover:border-white/40"
              }`}
            >
              {l.label}
            </button>
          );
        })}
      </div>
      <p className="text-[10px] text-white/30 mt-1">
        {LEVELS.find((l) => l.key === level)?.hint}
      </p>
    </div>
  );
}
