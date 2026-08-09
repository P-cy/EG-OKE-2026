"use client";

import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Toaster } from "@/components/Toaster";
import { CheckinModal } from "@/components/CheckinModal";
import { useCheckinNotify, useNotifyStore } from "@/lib/notify";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

// เปิด SSE + ครอบ login re-show (เรียก /me/at-prompt ตอนเปิดแอป/login)
function NotifyManager() {
  useCheckinNotify();
  const user = useAuth((s) => s.user);
  const hydrated = useAuth((s) => s.hydrated);
  const refreshUser = useAuth((s) => s.refreshUser);
  const show = useNotifyStore((s) => s.show);
  const pushedAt = useNotifyStore((s) => s.payload?.at);
  const qc = useQueryClient();

  // ★ พอถูกเช็คอิน → ดึงบัตรใหม่ทันที ไม่ต้องรอ poll รอบถัดไป (30 วิ)
  //   ผู้เข้างานจะเห็นแถบ "วันที่ N" เปลี่ยนเป็นเขียวพร้อมกับ modal ที่เด้ง
  useEffect(() => {
    if (!pushedAt) return;
    qc.invalidateQueries({ queryKey: ["my-tickets"] });
    qc.invalidateQueries({ queryKey: ["my-points"] });
    refreshUser().catch(() => {});   // ยอดเหรียญบน header
  }, [pushedAt, qc, refreshUser]);

  useEffect(() => {
    if (!hydrated || !user) return;
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (!token) return;
    api.getATPrompt()
      .then((res) => {
        if (res.show) {
          show({
            type: "checkin_ok",
            event_day: res.event_day!,
            coins_awarded: res.coins_awarded ?? 0,
            form_url: res.form_url ?? "",
            at: res.checked_in_at ?? new Date().toISOString(),
          });
        }
      })
      .catch(() => {});
  }, [hydrated, user?.id, show]);

  return null;
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // polling ที่ปลอดภัย: หยุดเมื่อ tab ซ่อน, retry backoff
            refetchIntervalInBackground: false,
            retry: 3,
            retryDelay: (n) => Math.min(1000 * 2 ** n, 30000),
            staleTime: 10_000,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster />
      <CheckinModal />
      <NotifyManager />
    </QueryClientProvider>
  );
}
