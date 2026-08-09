"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { BrowserMultiFormatReader } from "@zxing/browser";
import { api, type CheckinOut, type CheckinResult } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { toast } from "@/components/Toaster";
import { formatTime } from "@/lib/format";
import { useAuth } from "@/lib/auth";

// Scanner PWA — offline-first
// หลักการหน้างาน:
//   - staff เลือกวัน (1/2/3) ครั้งเดียว → จำไว้ใน localStorage (รีเฟรชแล้วไม่เด้งกลับวัน 1)
//   - รับได้ 3 ทาง: กล้องสแกน QR / พิมพ์รหัสบัตร EGOKE26-XXXX / พิมพ์รหัสนักศึกษา 7 หลัก
//   - ผลลัพธ์เป็น "ภาษาไทย + บอกว่าต้องทำอะไรต่อ" ไม่ใช่ code ดิบ
//   - เน็ตหลุด → เก็บคิวใน localStorage แล้ว sync ตอนกลับมา (สถานะเป็น "รอส่ง" ไม่ใช่ "ผ่าน")
export default function ScanPage() {
  return (
    <ProtectedRoute roles={["staff", "admin"]}>
      <ScannerContent />
    </ProtectedRoute>
  );
}

interface QueueItem {
  idempotency_key: string;
  payload: string;
  event_day: number;
  gate: string;
  device_id: string;
  scanned_at: string;
}

interface RecentRow {
  at: number;
  result: CheckinResult;
  name: string;
  day: number;
  // โหมดจ่ายเหรียญ: จ่ายไปกี่เหรียญ (โหมดเช็คอินไม่มีค่านี้)
  coins?: number;
}

const DAY_KEY = "scan:event_day";
const QUEUE_KEY = "scan:queue";
const DEVICE_KEY = "scan:device_id";
const MODE_KEY = "scan:mode";
const AMOUNT_KEY = "scan:amount";

// เครื่องสแกนเครื่องเดียวใช้ได้ 2 งาน — ประตูทางเข้า กับ จ่ายเหรียญที่บูธ
type ScanMode = "checkin" | "coins";

// ★ จ่ายเหรียญไม่ผูกกับกิจกรรมแล้ว — บูธเก็บค่าเล่นเป็นเงินสดเอง ระบบจ่ายรางวัลอย่างเดียว
//   ของเดิมบังคับให้ staff เลือก "กิจกรรม" ที่ admin ตั้งไว้ก่อนถึงจะสแกนได้
//   แปลว่าทุกบูธต้องมีคนไปสร้างรายการในระบบก่อน ซึ่งหน้างานไม่มีใครทำทัน
const PRESET_AMOUNTS = [20, 50, 100];
const MAX_AMOUNT = 1000;   // ตรงกับเพดานฝั่ง backend

// ★ สีและคำที่ staff เห็นเต็มจอ — ต้องอ่านจากระยะ 1 เมตรแล้วตัดสินใจได้ทันที
const RESULT_UI: Record<CheckinResult, { label: string; sub: string; bg: string; pass: boolean }> = {
  ok:                     { label: "ผ่าน",       sub: "เช็คอินสำเร็จ",             bg: "bg-neon-green", pass: true },
  duplicate:              { label: "เข้าแล้ว",   sub: "วันนี้เช็คอินไปแล้ว",        bg: "bg-neon-yellow", pass: true },
  queued:                 { label: "รอส่ง",      sub: "ไม่มีเน็ต — ยังไม่ยืนยัน",   bg: "bg-neon-blue",  pass: false },
  not_found:              { label: "ไม่พบ",      sub: "ไม่มีบัตรนี้ในระบบ",         bg: "bg-red-500",    pass: false },
  no_ticket:              { label: "ยังไม่มีบัตร", sub: "ต้องตั้งค่าโปรไฟล์ก่อน",   bg: "bg-red-500",    pass: false },
  invalid_sig:            { label: "อ่านไม่ได้",  sub: "รหัสไม่ถูกต้อง",            bg: "bg-red-500",    pass: false },
  revoked:                { label: "ถูกยกเลิก",  sub: "ห้ามให้เข้า",               bg: "bg-red-600",    pass: false },
  rotating_code_mismatch: { label: "รหัสไม่ตรง", sub: "อาจเป็นภาพแคปหน้าจอ",       bg: "bg-red-500",    pass: false },
  wrong_day:              { label: "ผิดวัน",     sub: "บัตรไม่ตรงวัน",             bg: "bg-red-500",    pass: false },
  expired:                { label: "หมดอายุ",    sub: "บัตรหมดอายุแล้ว",           bg: "bg-red-500",    pass: false },
  error:                  { label: "ผิดพลาด",    sub: "ลองใหม่อีกครั้ง",           bg: "bg-red-500",    pass: false },
  // ★ ชนโควตา — ส้ม ไม่ใช่แดง เพราะไม่ใช่ "บัตรมีปัญหา" แต่เป็น "จ่ายไม่ได้ตอนนี้"
  //   staff ต้องแยกออกทันที: แดง = ไล่กลับไปแก้บัตร / ส้ม = บัตรปกติ แต่โควตาหมด
  limit_reached:          { label: "เกินโควตา",  sub: "จ่ายไม่ได้",                bg: "bg-orange-400", pass: false },
};

function newKey(): string {
  // crypto.randomUUID มีเฉพาะ secure context (https / localhost)
  // บนมือถือที่เปิดผ่าน LAN IP แบบ http จะ undefined → ต้องมีตัวสำรอง
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  } catch {}
  return `k-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function ScannerContent() {
  const isAdmin = useAuth((s) => s.hasRole("admin"));
  const [mode, setMode] = useState<ScanMode>("checkin");
  const [amount, setAmount] = useState(20);
  const [customAmount, setCustomAmount] = useState("");
  const [day, setDay] = useState(1);
  const [manual, setManual] = useState("");
  const [lastResult, setLastResult] = useState<CheckinOut | null>(null);
  const [recent, setRecent] = useState<RecentRow[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [online, setOnline] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [cameraActive, setCameraActive] = useState(false);
  const [secure, setSecure] = useState(true);
  const [deviceId, setDeviceId] = useState("scanner");
  const [busy, setBusy] = useState(false);
  // โควตาที่ staff คนนี้ใช้ไปวันนี้ — backend ส่งกลับมาทุกครั้งที่จ่ายสำเร็จ
  const [quota, setQuota] = useState<{ used: number; cap: number } | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const controlsRef = useRef<{ stop: () => void } | null>(null);
  const lastScanRef = useRef<{ code: string; at: number } | null>(null);
  const dayRef = useRef(1);
  const modeRef = useRef<ScanMode>("checkin");
  const amountRef = useRef(20);
  const clearTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // ── boot: กู้สถานะที่ต้องคงข้ามการรีเฟรช ──
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);

    // ★ วันที่เลือกต้องคงอยู่ — staff รีเฟรชกลางงานแล้วเด้งกลับวัน 1 = ข้อมูลเข้าวันผิด
    const savedDay = Number(localStorage.getItem(DAY_KEY));
    if (savedDay >= 1 && savedDay <= 3) { setDay(savedDay); dayRef.current = savedDay; }

    // โหมดกับจำนวนเหรียญก็ต้องคงอยู่ — บูธเดิมจ่ายเท่าเดิมทั้งวัน รีเฟรชแล้วต้องไม่เด้งกลับ
    const savedMode = localStorage.getItem(MODE_KEY);
    if (savedMode === "coins" || savedMode === "checkin") {
      setMode(savedMode); modeRef.current = savedMode;
    }
    const savedAmount = Number(localStorage.getItem(AMOUNT_KEY));
    if (savedAmount >= 1 && savedAmount <= MAX_AMOUNT) {
      setAmount(savedAmount); amountRef.current = savedAmount;
      if (!PRESET_AMOUNTS.includes(savedAmount)) setCustomAmount(String(savedAmount));
    }

    // device_id คงที่ต่อเครื่อง — ไม่งั้น rate limit ต่อ device ไม่มีความหมาย
    let dev = localStorage.getItem(DEVICE_KEY);
    if (!dev) {
      dev = `scanner-${Math.random().toString(36).slice(2, 8)}`;
      localStorage.setItem(DEVICE_KEY, dev);
    }
    setDeviceId(dev);

    const raw = localStorage.getItem(QUEUE_KEY);
    if (raw) { try { setQueue(JSON.parse(raw)); } catch {} }

    // กล้องต้องการ secure context — บอกล่วงหน้าดีกว่าให้กดแล้วเงียบ
    setSecure(window.isSecureContext);

    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
      try { controlsRef.current?.stop(); } catch {}
      clearTimeout(clearTimer.current);
    };
  }, []);

  function pickDay(d: number) {
    setDay(d);
    dayRef.current = d;
    localStorage.setItem(DAY_KEY, String(d));
    toast(`เปลี่ยนเป็นวันที่ ${d} แล้ว`, "success");
  }

  function pickMode(m: ScanMode) {
    setMode(m);
    modeRef.current = m;
    localStorage.setItem(MODE_KEY, m);
    setLastResult(null);
    toast(m === "checkin" ? "โหมดเช็คอินเข้างาน" : "โหมดจ่ายเหรียญ", "success");
  }

  function pickAmount(n: number) {
    setAmount(n);
    amountRef.current = n;
    localStorage.setItem(AMOUNT_KEY, String(n));
    if (PRESET_AMOUNTS.includes(n)) setCustomAmount("");
  }

  function persist(items: QueueItem[]) {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(items));
  }

  function feedback(result: CheckinResult) {
    try {
      const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.frequency.value = result === "ok" ? 880 : result === "duplicate" ? 440 : 220;
      gain.gain.value = 0.2;
      osc.start();
      setTimeout(() => { osc.stop(); ctx.close(); }, 200);
    } catch {}
    try {
      navigator.vibrate?.(result === "ok" ? 100 : result === "duplicate" ? [50, 50, 50] : 300);
    } catch {}
  }

  const submit = useCallback(async (code: string) => {
    const value = code.trim();
    if (!value || value.length < 6) {
      toast("รหัสสั้นเกินไป — สแกน QR หรือพิมพ์รหัสนักศึกษา 7 หลัก", "warn");
      return;
    }

    const eventDay = dayRef.current;
    const idempotency_key = newKey();
    const scanned_at = new Date().toISOString();
    const dev = localStorage.getItem(DEVICE_KEY) || "scanner";

    const show = (res: CheckinOut) => {
      setLastResult(res);
      feedback(res.result);
      setRecent((prev) => [
        {
          at: Date.now(), result: res.result,
          name: res.user?.display_name || value, day: eventDay,
          coins: modeRef.current === "coins" ? res.coins_awarded : undefined,
        },
        ...prev,
      ].slice(0, 10));
      // ★ ล้างจอใน 10 วิ — กันผลของคนก่อนหน้าค้างแล้ว staff เผลอโบกคนถัดไปผ่าน
      clearTimeout(clearTimer.current);
      clearTimer.current = setTimeout(() => setLastResult(null), 10_000);
    };

    // ── โหมดจ่ายเหรียญ ── (ไม่มี offline queue — บูธต้องรู้ผลทันทีว่าจ่ายไปหรือยัง)
    if (modeRef.current === "coins") {
      const amt = amountRef.current;
      if (!amt || amt < 1) {
        toast("ใส่จำนวนเหรียญก่อนสแกน", "warn");
        return;
      }
      setBusy(true);
      try {
        const res = await api.staffGrantCoins(value, amt, dev, idempotency_key);
        if (res.staff_cap_today) {
          setQuota({ used: res.staff_used_today ?? 0, cap: res.staff_cap_today });
        }
        // map ผลเข้าหน้าตาเดียวกับเช็คอิน เพื่อใช้จอผลลัพธ์ร่วมกัน
        show({
          result: res.result,
          event_day: eventDay,
          coins_awarded: res.coins_awarded,
          message: res.message ?? undefined,
          user: res.user,
          matched_by: res.matched_by,
        });
      } catch (e: any) {
        show({
          result: "error", event_day: eventDay, coins_awarded: 0,
          message: e?.message || "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้",
        });
      } finally {
        setBusy(false);
      }
      return;
    }

    if (!navigator.onLine) {
      const item: QueueItem = {
        idempotency_key, payload: value, event_day: eventDay,
        gate: "MAIN", device_id: dev, scanned_at,
      };
      const next = [...queue, item];
      setQueue(next); persist(next);
      // ★ ห้ามโชว์ "ผ่าน" — ยังไม่มีใครยืนยันว่าบัตรใบนี้ใช้ได้จริง
      show({ result: "queued", event_day: eventDay, coins_awarded: 0,
             message: "เก็บไว้ในคิวแล้ว จะส่งอัตโนมัติเมื่อเน็ตกลับมา" });
      return;
    }

    setBusy(true);
    try {
      const res = await api.checkin(
        { payload: value, event_day: eventDay, gate: "MAIN", device_id: dev, scanned_at },
        idempotency_key,
      );
      show(res);
    } catch (e: any) {
      show({
        result: "error", event_day: eventDay, coins_awarded: 0,
        message: e?.message || "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้",
      });
    } finally {
      setBusy(false);
    }
  }, [queue]);

  async function startCamera() {
    if (!videoRef.current) return;
    if (!window.isSecureContext) {
      toast("เปิดกล้องไม่ได้ ต้องเป็น https หรือ localhost — ใช้ช่องพิมพ์รหัสด้านล่างแทน", "error");
      return;
    }
    try {
      const reader = new BrowserMultiFormatReader();
      controlsRef.current = await reader.decodeFromVideoDevice(
        undefined, videoRef.current, (result) => {
          if (!result) return;
          const text = result.getText();
          // debounce: รหัสเดิมภายใน 3 วิ = ไม่ส่งซ้ำ (กล้องอ่านซ้ำหลายเฟรมต่อวินาที)
          const now = Date.now();
          if (lastScanRef.current?.code === text && now - lastScanRef.current.at < 3000) return;
          lastScanRef.current = { code: text, at: now };
          submit(text);
        },
      );
      setCameraActive(true);
    } catch (e: any) {
      toast(e?.message || "เปิดกล้องไม่ได้ — ใช้ช่องพิมพ์รหัสด้านล่างแทน", "error");
    }
  }

  function stopCamera() {
    try { controlsRef.current?.stop(); } catch {}
    controlsRef.current = null;
    setCameraActive(false);
  }

  const syncQueue = useCallback(async () => {
    if (!queue.length || !navigator.onLine) return;
    setSyncing(true);
    const sending = queue;
    try {
      const res = await api.checkinBatch(
        sending.map((q) => ({
          payload: q.payload, event_day: q.event_day,
          gate: q.gate, device_id: q.device_id, scanned_at: q.scanned_at,
        })),
      );
      // ★ ทิ้งเฉพาะรายการที่ backend ตอบผลแน่นอนแล้ว — ที่ error ต้องคาไว้ลองใหม่
      //   (ของเดิมล้างทั้งคิวเสมอ = สแกนที่ล้มเหลวหายไปเงียบๆ)
      const failedIdx = new Set(
        res.results.map((r, i) => (r.result === "error" ? i : -1)).filter((i) => i >= 0),
      );
      const left = sending.filter((_, i) => failedIdx.has(i));
      setQueue(left); persist(left);
      const okCount = res.results.filter((r) => r.result === "ok").length;
      toast(
        left.length
          ? `ส่งแล้ว ${sending.length - left.length} (ผ่าน ${okCount}) · ค้าง ${left.length}`
          : `ส่งครบ ${sending.length} รายการ (ผ่าน ${okCount})`,
        left.length ? "warn" : "success",
      );
    } catch (e: any) {
      toast(e?.message || "sync ไม่สำเร็จ จะลองใหม่", "error");
    } finally {
      setSyncing(false);
    }
  }, [queue]);

  useEffect(() => {
    if (online && queue.length) syncQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online]);

  const ui = lastResult ? RESULT_UI[lastResult.result] ?? RESULT_UI.error : null;
  const paidTotal = recent.reduce((sum, r) => sum + (r.coins ?? 0), 0);

  // ★ คำบรรยายใต้ตัวใหญ่ต้องตรงกับงานที่ทำอยู่
  //   RESULT_UI เขียนไว้สำหรับเช็คอิน ถ้าใช้ตรงๆ ในโหมดจ่ายเหรียญจะขึ้นว่า
  //   "เช็คอินสำเร็จ · จ่าย 20 เหรียญ" ซึ่ง staff อ่านแล้วไม่รู้ว่าตกลงทำอะไรไป
  const resultSub = !lastResult || !ui
    ? ""
    : mode === "checkin"
      ? `${ui.sub} · วันที่ ${lastResult.event_day ?? day}`
      : lastResult.result === "ok"
        ? `จ่าย ${lastResult.coins_awarded} เหรียญแล้ว`
        : lastResult.result === "duplicate"
          ? "เพิ่งจ่ายไปแล้ว ไม่จ่ายซ้ำ"
          : ui.sub;

  return (
    <div className="min-h-screen flex flex-col">
      {/* ── แถบกลับ — บางที่สุดเท่าที่จะทำได้ ไม่กินที่จอผลลัพธ์ ──
          ★ ของเดิมหน้านี้ไม่มีทางออกเลย เข้ามาแล้วต้องกด back ของ browser
            หรือพิมพ์ URL ใหม่ ซึ่งบนมือถือที่เปิดแบบ PWA ไม่มีปุ่ม back ให้กด */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/10 text-xs font-mono shrink-0">
        <Link href={isAdmin ? "/admin" : "/staff"} className="text-white/40 hover:text-white">
          กลับ
        </Link>
        <span className={mode === "checkin" ? "text-neon-green" : "text-neon-pink"}>
          {mode === "checkin" ? `เช็คอิน วันที่ ${day}` : `จ่าย ${amount} เหรียญ`}
        </span>
      </div>

      {/* ── ผลลัพธ์เต็มจอ — เห็นจากมุมตา ── */}
      {lastResult && ui ? (
        <div className={`${ui.bg} flex-1 flex flex-col items-center justify-center text-black min-h-[42vh] p-4 text-center`}>
          <p className="font-mono text-6xl sm:text-7xl font-bold leading-none">
            {mode === "coins" && lastResult.result === "ok" ? "จ่ายแล้ว" : ui.label}
          </p>
          <p className="text-lg mt-1 font-medium">{resultSub}</p>

          {lastResult.user && (
            <>
              {lastResult.user.avatar_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={lastResult.user.avatar_url} alt="" className="w-24 h-24 rounded-full mt-3 border-4 border-black object-cover" />
              )}
              <p className="text-3xl font-bold mt-2">{lastResult.user.display_name || "-"}</p>
              {/* ★ ชื่อจริงจาก Google — ระบบเปิดรับอีเมลทุก domain แล้ว
                  คนนอกมหิดลไม่มีรหัสนักศึกษาให้เทียบ ชื่อจริงคือสิ่งเดียวที่ staff ใช้ยืนยันตัวตนได้ */}
              {lastResult.user.full_name && lastResult.user.full_name !== lastResult.user.display_name && (
                <p className="text-lg opacity-80">{lastResult.user.full_name}</p>
              )}
              <p className="text-base">{lastResult.user.student_id || ""}</p>
            </>
          )}

          {/* ★ บอกว่าคนนี้เข้ามาแล้ววันไหนบ้าง — staff เห็นภาพรวมทันที */}
          {lastResult.ticket?.checked_in_days && (
            <div className="flex gap-1.5 mt-3">
              {[1, 2, 3].map((d) => (
                <span
                  key={d}
                  className={`px-2 py-0.5 text-sm font-mono border-2 border-black ${
                    lastResult.ticket!.checked_in_days!.includes(d) ? "bg-black text-white" : "opacity-40"
                  }`}
                >
                  วัน{d}
                </span>
              ))}
            </div>
          )}

          {lastResult.coins_awarded > 0 && <p className="text-xl mt-2 font-bold">+{lastResult.coins_awarded} coin</p>}
          {/* ข้อความจาก backend — บอกว่าต้องทำอะไรต่อ */}
          {lastResult.message && !ui.pass && (
            <p className="text-sm mt-3 max-w-md opacity-80">{lastResult.message}</p>
          )}
          {lastResult.checked_in_at && ui.pass && (
            <p className="text-xs mt-2 opacity-60">เมื่อ {formatTime(lastResult.checked_in_at)}</p>
          )}
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center min-h-[24vh] text-white/30 font-mono">
          <p className="text-2xl">พร้อมสแกน</p>
          <p className="text-sm mt-1">
            {mode === "checkin" ? `เช็คอิน วันที่ ${day}` : `จ่าย ${amount} เหรียญ`}
          </p>
        </div>
      )}

      <div className="p-4 bg-bg-deep space-y-4">
        {/* ── โหมด: ประตูทางเข้า หรือ บูธกิจกรรม ── */}
        <div className="flex gap-2">
          <button
            onClick={() => pickMode("checkin")}
            className={`flex-1 px-4 py-3 font-mono ${mode === "checkin" ? "neon-border-blue text-neon-blue bg-neon-blue/10" : "border border-white/20 text-white/40"}`}
          >
            เช็คอินเข้างาน
          </button>
          <button
            onClick={() => pickMode("coins")}
            className={`flex-1 px-4 py-3 font-mono ${mode === "coins" ? "neon-border-pink text-neon-pink bg-neon-pink/10" : "border border-white/20 text-white/40"}`}
          >
            จ่ายเหรียญ
          </button>
        </div>

        {/* ── เลือกวัน (โหมดเช็คอิน) ── */}
        {mode === "checkin" ? (
          <div>
            <p className="text-xs text-white/40 mb-2 font-mono">
              วันที่เช็คอิน — ตรวจให้ตรงก่อนเริ่มสแกน (ระบบจำค่านี้ไว้)
            </p>
            <div className="flex gap-2">
              {[1, 2, 3].map((d) => (
                <button
                  key={d}
                  onClick={() => pickDay(d)}
                  className={`flex-1 px-4 py-3 font-mono text-lg ${day === d ? "neon-border-pink text-neon-pink bg-neon-pink/10" : "border border-white/20 text-white/50"}`}
                >
                  วันที่ {d}
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* ── เลือกจำนวนเหรียญ (โหมดจ่ายเหรียญ) ── */
          <div>
            <p className="text-xs text-white/40 mb-2 font-mono">
              จ่ายครั้งละกี่เหรียญ — เลือกก่อนเริ่มสแกน (ระบบจำค่านี้ไว้)
            </p>

            <div className="flex gap-2">
              {PRESET_AMOUNTS.map((n) => (
                <button
                  key={n}
                  onClick={() => pickAmount(n)}
                  className={`flex-1 px-4 py-4 font-mono text-2xl ${
                    amount === n
                      ? "neon-border-pink text-neon-pink bg-neon-pink/10"
                      : "border border-white/20 text-white/50"
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>

            {/* พิมพ์เอง — บูธที่จ่ายไม่ตรงกับปุ่มสำเร็จรูป */}
            <div className="flex gap-2 mt-2 items-center">
              <span className="text-xs text-white/40 font-mono shrink-0">หรือพิมพ์เอง</span>
              <input
                value={customAmount}
                onChange={(e) => {
                  const raw = e.target.value.replace(/\D/g, "").slice(0, 4);
                  setCustomAmount(raw);
                  const n = Number(raw);
                  // อัปเดตค่าที่จะจ่ายทันทีที่พิมพ์ถูกช่วง — ไม่ต้องกดยืนยันอีกปุ่ม
                  if (n >= 1 && n <= MAX_AMOUNT) pickAmount(n);
                }}
                inputMode="numeric"
                className={`flex-1 bg-bg-deep px-3 py-2.5 text-white font-mono text-lg ${
                  customAmount && !PRESET_AMOUNTS.includes(Number(customAmount))
                    ? "neon-border-pink"
                    : "border border-white/20"
                }`}
              />
              <span className="text-sm text-white/40 font-mono shrink-0">เหรียญ</span>
            </div>

            {customAmount && Number(customAmount) > MAX_AMOUNT && (
              <p className="text-xs text-red-400 mt-1">
                จ่ายได้สูงสุด {MAX_AMOUNT} เหรียญต่อครั้ง
              </p>
            )}

            {/* ★ ยืนยันจำนวนตัวใหญ่ — staff ต้องเห็นชัดก่อนส่องกล้อง
                จ่ายผิดจำนวนแล้วต้องให้ admin ตามแก้ทีละคน */}
            <div className="mt-3 border border-neon-yellow/40 bg-neon-yellow/5 px-4 py-3 text-center">
              <p className="text-xs text-white/50">สแกนแล้วจะจ่าย</p>
              <p className="font-mono text-3xl text-neon-yellow">{amount} เหรียญ</p>
            </div>

            {/* ★ โควตาของตัวเอง — ต้องเห็นก่อนจะชน ไม่ใช่รู้ตอนถูกปฏิเสธกลางคิว
                ถ้าเหลือน้อยจะได้ไปตาม admin ล่วงหน้า */}
            {quota && (
              <div className="mt-2 text-xs font-mono flex justify-between text-white/40">
                <span>โควตาวันนี้ของคุณ</span>
                <span className={quota.used / quota.cap > 0.8 ? "text-neon-yellow" : ""}>
                  ใช้ไป {quota.used.toLocaleString("th-TH")} / {quota.cap.toLocaleString("th-TH")}
                </span>
              </div>
            )}

            <p className="text-[11px] text-white/30 mt-2 leading-relaxed">
              ระบบจำกัดว่าคนหนึ่งรับจากคุณได้เท่าไหร่ต่อวัน และรับรวมจากทุกบูธได้เท่าไหร่ต่อวัน
              ถ้าขึ้น &quot;เกินโควตา&quot; แปลว่าบัตรปกติ แต่จ่ายเพิ่มไม่ได้แล้ว — อ่านข้อความบนจอ
            </p>
          </div>
        )}

        {/* ── กล้อง ── */}
        <RetroCard glow="pink" title="1. สแกน QR ด้วยกล้อง">
          <video ref={videoRef} autoPlay playsInline muted className={`w-full max-w-sm mx-auto rounded ${cameraActive ? "block" : "hidden"}`} />
          {!cameraActive && (
            <p className="text-center text-white/40 text-sm py-6 font-mono">
              {secure ? "กล้องปิดอยู่ — กดเปิดด้านล่าง" : "เครื่องนี้เปิดกล้องไม่ได้ (ไม่ใช่ https/localhost) — ใช้วิธีที่ 2 แทน"}
            </p>
          )}
          {secure && (
            <div className="flex gap-2 mt-3">
              {!cameraActive ? (
                <NeonButton variant="pink" onClick={startCamera} className="flex-1">เปิดกล้อง</NeonButton>
              ) : (
                <NeonButton variant="ghost" onClick={stopCamera} className="flex-1">ปิดกล้อง</NeonButton>
              )}
            </div>
          )}
        </RetroCard>

        {/* ── พิมพ์รหัส (ทางถอยที่ใช้ได้จริงบนคอม/เมื่อกล้องไม่ติด) ── */}
        <RetroCard glow="blue" title="2. พิมพ์รหัส (ไม่ต้องใช้กล้อง)">
          <form
            onSubmit={(e) => { e.preventDefault(); const v = manual.trim(); if (v) { submit(v); setManual(""); } }}
            className="flex gap-2"
          >
            <input
              value={manual}
              onChange={(e) => setManual(e.target.value)}
              autoComplete="off"
              className="flex-1 bg-bg-deep neon-border-blue px-3 py-3 text-white font-mono text-sm"
            />
            <NeonButton variant="pink" type="submit" loading={busy}>เช็คอิน</NeonButton>
          </form>
          <p className="text-[11px] text-white/40 mt-2 leading-relaxed">
            ใส่ได้ 3 แบบ: QR payload เต็ม · รหัสบัตร <span className="font-mono text-neon-blue">EGOKE26-XXXXXXXX</span> (ผู้เข้างานเปิดหน้าบัตรให้ดู) · รหัสนักศึกษา 7 หลัก
          </p>
        </RetroCard>

        {/* ── สถานะ + ทางลัด ── */}
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <span className={`inline-block w-3 h-3 rounded-full ${online ? "bg-neon-green" : "bg-red-500"}`} />
            <span className="text-sm text-white/60">{online ? "ออนไลน์" : "ออฟไลน์"}</span>
            {queue.length > 0 && (
              <span className="text-sm text-neon-yellow font-mono ml-2">รอส่ง {queue.length}</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {queue.length > 0 && (
              <NeonButton variant="ghost" loading={syncing} onClick={syncQueue}>ส่งตอนนี้</NeonButton>
            )}
            {/* ★ staff เข้า /admin/attendees ไม่ได้ (admin เท่านั้น) — ของเดิมชี้ไปที่นั่น
                staff กดแล้วโดนเด้งกลับหน้าแรกโดยไม่มีคำอธิบาย */}
            <Link href={isAdmin ? "/admin/attendees" : "/staff/attendees"}>
              <NeonButton variant="ghost">ค้นจากรายชื่อ</NeonButton>
            </Link>
          </div>
        </div>

        {/* ── 10 คนล่าสุด — staff ตรวจย้อนหลังได้ว่าเพิ่งสแกนใครไป ── */}
        {recent.length > 0 && (
          <RetroCard glow="blue" title={`สแกนล่าสุด (${recent.length})`}>
            {mode === "coins" && paidTotal > 0 && (
              <p className="text-sm text-neon-yellow font-mono mb-2 pb-2 border-b border-white/10">
                จ่ายไปแล้ว {paidTotal} เหรียญ (นับเฉพาะที่เห็นในรายการนี้)
              </p>
            )}
            <ul className="space-y-1 text-sm">
              {recent.map((r) => (
                <li key={r.at} className="flex justify-between gap-2 font-mono">
                  <span className="truncate text-white/70">{r.name}</span>
                  <span className={
                    r.result === "ok" ? "text-neon-green"
                    : r.result === "duplicate" ? "text-neon-yellow"
                    : r.result === "queued" ? "text-neon-blue" : "text-red-400"
                  }>
                    {r.coins !== undefined
                      ? `${r.result === "ok" ? "จ่ายแล้ว" : RESULT_UI[r.result]?.label ?? r.result} · ${r.coins} เหรียญ`
                      : `${RESULT_UI[r.result]?.label ?? r.result} · วัน${r.day}`}
                  </span>
                </li>
              ))}
            </ul>
          </RetroCard>
        )}
      </div>
    </div>
  );
}
