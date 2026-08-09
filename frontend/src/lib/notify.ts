// notify store + SSE hook — รับ push สดตอนถูกเช็คอิน แล้วเด้ง modal ฟอร์ม Attendance
"use client";

import { useEffect } from "react";
import { create } from "zustand";
import { useAuth } from "./auth";
import { refreshAccessToken } from "./api";
import type { CheckinNotifyPayload } from "./api";

interface NotifyState {
  open: boolean;
  payload: CheckinNotifyPayload | null;
  show: (p: CheckinNotifyPayload) => void;
  close: () => void;
}

export const useNotifyStore = create<NotifyState>((set) => ({
  open: false,
  payload: null,
  show: (p) => set({ open: true, payload: p }),
  close: () => set({ open: false }),
}));

const SSE_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/v1";

// ★ เปิด SSE เมื่อ login อยู่ → รับ event checkin_ok → เด้ง modal
//   EventSource ส่ง Authorization header ไม่ได้ → ส่ง token ใน query
//   onerror → close + เปิดใหม่ใน 5s ด้วย token ใหม่ (กัน token refresh + reconnect storm)
export function useCheckinNotify() {
  const user = useAuth((s) => s.user);
  const hydrated = useAuth((s) => s.hydrated);

  useEffect(() => {
    if (!hydrated || !user) return;
    let es: EventSource | null = null;
    let stopped = false;
    let fails = 0;
    let retry: ReturnType<typeof setTimeout>;

    const open = () => {
      const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
      if (!token) return;
      es = new EventSource(`${SSE_BASE}/me/stream?token=${encodeURIComponent(token)}`);

      es.onopen = () => { fails = 0; };
      es.addEventListener("checkin_ok", (e: MessageEvent) => {
        try {
          useNotifyStore.getState().show(JSON.parse(e.data));
        } catch {}
      });

      es.onerror = async () => {
        es?.close();
        if (stopped) return;
        fails += 1;
        // ★ access token อายุ 15 นาที — พอหมดอายุ stream จะโดน 401 ทุกครั้งที่ต่อใหม่
        //   ถ้าไม่ refresh ก่อน จะวนยิง 401 ทุก 5 วิ ไปตลอดจนกว่าจะมี API call อื่นไป refresh ให้
        await refreshAccessToken().catch(() => false);
        if (stopped) return;
        // backoff 5s → 10s → 20s → 30s (เพดาน) กัน reconnect storm ตอนเซิร์ฟเวอร์ restart
        const delay = Math.min(5000 * 2 ** (fails - 1), 30_000);
        retry = setTimeout(open, delay);
      };
    };
    open();

    return () => {
      stopped = true;
      clearTimeout(retry);
      es?.close();
    };
  }, [hydrated, user?.id]);
}
