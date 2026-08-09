"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, setToken } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toast } from "@/components/Toaster";
import { Spinner } from "@/components/Spinner";

export default function LoginPage() {
  return (
    <Suspense fallback={<LoadingScreen />}>
      <LoginInner />
    </Suspense>
  );
}

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { setUser, user } = useAuth();
  const [loading, setLoading] = useState(false);
  const [handling, setHandling] = useState(false);

  // ถ้า login แล้วและเข้า /login เอง → ไป onboarding ถ้ายัง ไม่งั้นกลับหน้าแรก
  //   ★ อย่ากลับหน้าแรกตอน needs_onboarding ไม่งั้นคนใหม่เข้าไม่ได้
  //   ★ ต้องเช็ค token ด้วย ไม่ใช่ดูแค่ user
  //     Layout ตัดสินด้วย token แต่ตรงนี้เคยตัดสินด้วย user อย่างเดียว
  //     พอสองที่ไม่ตรงกัน (user ค้างแต่ token หาย) จะเด้งกันไปมาไม่หยุด
  //     / -> /login -> / -> /login ... และใน dev จะเห็นเป็น compile สลับ render
  useEffect(() => {
    if (!user || params.get("code")) return;
    if (typeof window !== "undefined" && !localStorage.getItem("access_token")) return;
    router.replace(user.needs_onboarding ? "/onboarding" : "/");
  }, [user, params, router]);

  // รอรับ callback จาก Google: /login?code=...&state=...
  useEffect(() => {
    const code = params.get("code");
    const state = params.get("state");
    if (code && state) {
      setHandling(true);
      api.googleCallback(code, state)
        .then((res) => {
          setToken(res.access_token);
          setUser(res.user);
          toast("เข้าสู่ระบบสำเร็จ", "success");
          router.replace(res.user.needs_onboarding ? "/onboarding" : "/");
        })
        .catch((e) => {
          // ★ ถ้า state หมดอายุ/invalid → เงียบๆ กลับไป login เริ่มใหม่ ไม่ต้องแจ้งเตือน
          //   เกิดบ่อยตอนเปิดหน้า login ทิ้งไว้นานหรือ refresh ตอน callback
          if (e?.code !== "OAUTH_STATE_INVALID" && e?.code !== "UNAUTHORIZED") {
            toast(e.message || "เข้าสู่ระบบไม่สำเร็จ", "error");
          }
          router.replace("/login");
        })
        .finally(() => setHandling(false));
    }
  }, [params, router, setUser]);

  async function googleLogin() {
    setLoading(true);
    try {
      const redirect = `${window.location.origin}/login`;
      const res = await api.googleLoginStart(redirect);
      window.location.href = res.authorize_url;
    } catch (e: any) {
      toast(e.message || "เปิดหน้า Google ไม่ได้", "error");
      setLoading(false);
    }
  }

  if (handling) return <LoadingScreen label="กำลังเข้าสู่ระบบ..." />;

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden">
      {/* sun glow ด้านหลัง */}
      <div
        className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[120vmin] h-[120vmin] rounded-full pointer-events-none"
        style={{
          background:
            "radial-gradient(circle, rgba(255,45,149,0.25) 0%, rgba(176,38,255,0.15) 40%, transparent 70%)",
        }}
      />

      <div className="relative z-10 w-full max-w-md text-center">
        {/* โลโก้ */}
        <div className="mb-10">
          <h1
            className="font-mono text-5xl sm:text-7xl neon-text-pink tracking-[0.2em] animate-flicker"
            style={{ fontWeight: 700 }}
          >
            EG'OKE
          </h1>
          <p className="font-mono text-xl sm:text-3xl neon-text-blue tracking-[0.3em] mt-2">
            2026
          </p>
          <div className="mt-4 h-px w-32 mx-auto bg-gradient-to-r from-transparent via-neon-purple to-transparent" />
          <p className="mt-4 text-white/40 font-mono text-sm tracking-widest">
            INSERT COIN TO BEGIN
          </p>
        </div>

        {/* ปุ่ม login กล่องเดียว */}
        <div className="retro-panel scanlines neon-border-blue rounded-md p-8">
          <button
            onClick={googleLogin}
            disabled={loading}
            className="group w-full flex items-center justify-center gap-3 py-4 px-6 transition-all hover:scale-[1.02] active:scale-95 disabled:opacity-50"
          >
            {loading ? (
              <Spinner size={28} />
            ) : (
              <>
                <GoogleIcon />
                <span className="font-mono text-lg neon-text-blue tracking-wider">
                  เข้าสู่ระบบด้วย Google
                </span>
              </>
            )}
          </button>
          <p className="mt-5 text-xs text-white/30 font-mono">
            เข้าสู่ระบบ = ยอมรับเงื่อนไขและนโยบายความเป็นส่วนตัว (PDPA)
          </p>
        </div>

        <p className="mt-8 text-white/20 font-mono text-xs tracking-widest">
          MAHIDOL UNIVERSITY · EG'OKE 2026
        </p>
      </div>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1Z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84Z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84C6.71 7.3 9.14 5.38 12 5.38Z"
        fill="#EA4335"
      />
    </svg>
  );
}

function LoadingScreen({ label = "กำลังโหลด..." }: { label?: string }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-4">
      <Spinner size={48} />
      <p className="text-white/60 font-mono">{label}</p>
    </div>
  );
}
