"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Spinner } from "./Spinner";

interface Props {
  children: ReactNode;
  roles?: string[]; // ถ้าระบุ ต้องมี role นี้อย่างน้อย 1 ตัว (superadmin ผ่านได้หมด)
}

export function ProtectedRoute({ children, roles }: Props) {
  const router = useRouter();
  const { user, hydrated, refreshUser, hasRole } = useAuth();

  useEffect(() => {
    if (!hydrated) return;
    // มี token ใน localStorage แต่ยังไม่มี user → ดึงใหม่
    // ★ หรือ user เก่าที่เก็บใน localStorage ยังไม่มี coins_balance (migration จาก points) → ดึงใหม่ด้วย
    const token = typeof window !== "undefined" && localStorage.getItem("access_token");
    const needsRefresh = !user || (user as any).coins_balance === undefined;
    if (token && needsRefresh) refreshUser();
  }, [hydrated, user, refreshUser]);

  useEffect(() => {
    if (!hydrated) return;
    const token = typeof window !== "undefined" && localStorage.getItem("access_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    if (roles && user && !roles.some((r) => hasRole(r))) {
      router.replace("/");
    }
  }, [hydrated, user, roles, router, hasRole]);

  if (!hydrated || (!user && typeof window !== "undefined" && localStorage.getItem("access_token"))) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (!user) return null;

  if (roles && !roles.some((r) => hasRole(r))) return null;

  return <>{children}</>;
}
