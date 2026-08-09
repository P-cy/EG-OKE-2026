// auth store — เก็บ access token + user profile
// ใช้ zustand เพราะเบา และอ่าน/เขียน localStorage ตอน hydrate

"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { api, setToken, type User } from "./api";

interface AuthState {
  user: User | null;
  hydrated: boolean;
  setUser: (user: User | null) => void;
  setToken: (token: string | null) => void;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  hasRole: (role: string) => boolean;
}

export const useAuth = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      hydrated: false,
      setUser: (user) => set({ user }),
      setToken: (token) => setToken(token),
      logout: async () => {
        // ★ ไม่รอ backend — เคลียร์ฝั่ง client ก่อนเลย แล้วค่อยสั่ง revoke ฝั่ง server
        //   ถ้ารอ api.logout() จะช้าโดยเฉพาะตอน token หมดอายุ/เน็ตแย่
        setToken(null);
        set({ user: null });
        try {
          await api.logout();
        } catch {
          // ไม่สน — token ฝั่งเราเคลียร์แล้ว ฝั่ง server revoke ไม่สำเร็จก็ไม่เป็นไร
        }
        // ★ redirect ไป login ทันที
        if (typeof window !== "undefined") {
          window.location.href = "/login";
        }
      },
      refreshUser: async () => {
        try {
          const me = await api.getMe();
          set({ user: me });
        } catch {
          // token ไม่ valid → เคลียร์
          setToken(null);
          set({ user: null });
        }
      },
      hasRole: (role) => {
        const u = get().user;
        return !!u && (u.roles.includes(role) || u.roles.includes("superadmin"));
      },
    }),
    {
      name: "egoke-auth",
      storage: createJSONStorage(() => (typeof window !== "undefined" ? localStorage : (undefined as any))),
      partialize: (s) => ({ user: s.user }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.hydrated = true;

          // ★ token คือแหล่งความจริงเดียว — ไม่มี token = ไม่มี user
          //   ของเดิมเก็บ user ไว้ใน localStorage แยกจาก access_token
          //   พอ token หายแต่ user ค้าง (หมดอายุ / logout แล้วปิดแท็บกลางคัน)
          //   จะได้สองความจริงที่ขัดกัน แล้วเกิด redirect loop:
          //     Layout เห็น "ไม่มี token" → เด้งไป /login
          //     หน้า /login เห็น "มี user" → เด้งกลับ /
          //   วนไม่หยุด และใน dev จะเห็นเป็น compile สลับ render สองหน้านี้ไปมา
          if (typeof window !== "undefined" && !localStorage.getItem("access_token")) {
            state.user = null;
            return;
          }
          // ★ migration: user เก่าใน localStorage อาจยังเก็บ points_balance (ก่อนเปลี่ยนเป็น coins)
          //   ถ้าไม่มี coins_balance ให้ย้ายจาก points_balance หรือตั้ง 0 กัน crash
          const u = state.user as any;
          if (u && (u.coins_balance === undefined || u.coins_balance === null)) {
            u.coins_balance = typeof u.points_balance === "number" ? u.points_balance : 0;
          }
        }
      },
    },
  ),
);
