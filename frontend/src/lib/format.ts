// format helpers — เวลา/จำนวน ภาษาไทย

export function formatCoins(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "0";
  return n.toLocaleString("th-TH");
}

// alias เดิม — กันพังจากโค้ดที่ยังเรียก formatPoints (จะค่อยๆ เปลี่ยน)
export const formatPoints = formatCoins;

/** แปลงเวลาจาก backend เป็น Date
 *
 * ★ ทำไมไม่ใช้ new Date(iso) ตรงๆ: ถ้าสตริงเป็นแบบ "2026-08-07T06:11:43.548000"
 *   (ไม่มี Z / ไม่มี offset) สเปก JS สั่งให้ตีความเป็น "เวลาท้องถิ่น"
 *   ค่าที่ backend ส่งคือ UTC → ทุกเวลาบนเว็บเพี้ยนไป 7 ชม.
 *   ("เพิ่งส่งเมื่อกี้" กลายเป็น "7 ชม.ที่แล้ว")
 *
 *   ต้นเหตุจริงแก้ที่ backend แล้ว (motor tz_aware=True) — ตัวนี้เป็นตาข่ายกันตก
 *   เผื่อมี endpoint ไหนหลุด หรือข้อมูลเก่าที่ cache ไว้
 */
export function parseServerTime(iso: string): Date {
  if (!iso) return new Date(NaN);
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  const looksNaive = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(iso) && !hasZone;
  return new Date(looksNaive ? `${iso.replace(" ", "T")}Z` : iso);
}

export function formatTime(iso: string): string {
  const d = parseServerTime(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("th-TH", {
    hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok",
  });
}

export function formatDateTime(iso: string): string {
  const d = parseServerTime(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("th-TH", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Bangkok",
  });
}

export function countdown(seconds: number): string {
  if (seconds <= 0) return "หมดเวลา";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}:${s.toString().padStart(2, "0")}` : `${s}s`;
}

export function relativeTime(iso: string): string {
  const t = parseServerTime(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  const sec = Math.floor(diff / 1000);
  // นาฬิกาเครื่องผู้ใช้เดินช้ากว่า server ได้ — กันไม่ให้ขึ้นค่าติดลบแปลกๆ
  if (sec < 60) return "เมื่อสักครู่";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} นาทีที่แล้ว`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} ชม.ที่แล้ว`;
  return `${Math.floor(hr / 24)} วันที่แล้ว`;
}

// IG handle แสดงเป็น "IG: @name"
export function igLabel(handle?: string | null): string {
  if (!handle) return "";
  const h = handle.startsWith("@") ? handle : `@${handle}`;
  return `IG: ${h}`;
}
