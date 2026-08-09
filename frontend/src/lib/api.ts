// API client — ต่อ backend FastAPI ที่ NEXT_PUBLIC_API_BASE
// หลักการ: ทุก fetch แนบ access token (จาก auth store) + สร้าง Idempotency-Key อัตโนมัติสำหรับ POST

const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
    public requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

/** UUID สำหรับ Idempotency-Key
 *
 * ★ ห้ามเรียก crypto.randomUUID() ตรงๆ — มันมีเฉพาะใน secure context
 *   (https หรือ localhost) พอเปิดเว็บผ่าน http://192.168.x.x บนมือถือหน้างาน
 *   ค่านี้เป็น undefined → TypeError → ทุก POST/PATCH/DELETE ทั้งเว็บพังหมด
 *   ทั้งเช็คอิน โหวต ส่งรูป หมุนวงล้อ — และ error ที่ขึ้นจะไม่บอกสาเหตุอะไรเลย
 */
export function newIdemKey(): string {
  const c = typeof crypto !== "undefined" ? crypto : undefined;
  if (c?.randomUUID) return c.randomUUID();
  if (c?.getRandomValues) {
    const b = c.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const hex = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return `k-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

/** ดาวน์โหลดไฟล์จาก endpoint ที่ต้องใช้ token
 *
 * ★ ใช้ <a href> ตรงๆ ไม่ได้ — browser ไม่แนบ Authorization header ให้
 *   จะได้ 401 กลับมาเป็นไฟล์ .csv ที่เปิดแล้วเจอ JSON error แทนข้อมูล
 *   ต้อง fetch เอง → blob → สร้าง object URL → กดให้เอง → คืน URL ทันที
 *   (ไม่คืน = blob ค้างในหน่วยความจำจนกว่าจะปิดแท็บ)
 */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${BASE}${path}`, { headers });
  if (!res.ok) {
    let msg = `ดาวน์โหลดไม่สำเร็จ (${res.status})`;
    try {
      const body = await res.json();
      msg = body?.error?.message || body?.message || msg;
    } catch {}
    throw new ApiError(res.status, "DOWNLOAD_FAILED", msg);
  }

  // ใช้ชื่อไฟล์ที่ server กำหนดมา (มี timestamp) ถ้าอ่านไม่ได้ค่อยใช้ชื่อสำรอง
  const disp = res.headers.get("content-disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(disp);
  const name = match?.[1] || fallbackName;

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem("access_token", token);
  else localStorage.removeItem("access_token");
}

export async function apiFetch<T>(
  path: string,
  opts: RequestInit & { idempotent?: boolean } = {},
): Promise<T> {
  const headers = new Headers(opts.headers);
  headers.set("Content-Type", "application/json");

  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  // POST/PUT/PATCH ที่เปลี่ยน state → ใส่ Idempotency-Key เสมอ
  if (opts.idempotent !== false && ["POST", "PUT", "PATCH", "DELETE"].includes((opts.method || "GET").toUpperCase())) {
    // ถ้ามี key ส่งมาเองใน body/header ใช้ของนั้น ไม่งั้นสุ่มใหม่
    if (!headers.has("Idempotency-Key")) {
      headers.set("Idempotency-Key", newIdemKey());
    }
  }

  let res = await fetch(`${BASE}${path}`, { ...opts, headers, credentials: "include" });

  if (res.status === 401) {
    // ลอง refresh ครั้งเดียว
    const ok = await tryRefresh();
    if (ok) {
      const t = getToken();
      if (t) headers.set("Authorization", `Bearer ${t}`);
      res = await fetch(`${BASE}${path}`, { ...opts, headers, credentials: "include" });
    } else {
      // ★ refresh ไม่ได้ = เซสชันหมดอายุจริง → เงียบๆ กลับ login ไม่ต้องโชว์ toast
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        setToken(null);
        window.location.href = "/login";
      }
    }
  }

  if (!res.ok) {
    let body: any = {};
    try {
      body = await res.json();
    } catch {}
    const err = body.error || {};
    throw new ApiError(
      res.status,
      err.code || "UNKNOWN",
      err.message || `HTTP ${res.status}`,
      err.details,
      err.request_id,
    );
  }

  // 204/202 อาจไม่มี body
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

let _refreshing: Promise<boolean> | null = null;
/** ขอ access token ใหม่ด้วย refresh cookie — export ให้ SSE ใช้ตอนโดน 401 */
export function refreshAccessToken(): Promise<boolean> {
  return tryRefresh();
}
async function tryRefresh(): Promise<boolean> {
  if (_refreshing) return _refreshing;
  _refreshing = (async () => {
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        setToken(null);
        return false;
      }
      const data = await res.json();
      setToken(data.access_token);
      return true;
    } catch {
      setToken(null);
      return false;
    } finally {
      _refreshing = null;
    }
  })();
  return _refreshing;
}

// ── typed endpoints ──────────────────────────────────────────────────
export const api = {
  // auth
  googleLoginStart: (redirect_uri?: string) =>
    apiFetch<{ authorize_url: string; state: string }>(`/auth/google/login${redirect_uri ? `?redirect_uri=${encodeURIComponent(redirect_uri)}` : ""}`, { method: "GET" }),
  googleCallback: (code: string, state: string) =>
    apiFetch<{ access_token: string; user: User }>(`/auth/google/callback`, { method: "POST", body: JSON.stringify({ code, state }) }),
  logout: () => apiFetch(`/auth/logout`, { method: "POST" }),

  // me
  getMe: () => apiFetch<User>(`/me`),
  patchMe: (body: Partial<ProfileUpdate>) =>
    apiFetch<User>(`/me`, { method: "PATCH", body: JSON.stringify(body) }),
  uploadAvatar: (image_data: string, mime = "image/jpeg") =>
    apiFetch<User>(`/me/avatar`, { method: "POST", body: JSON.stringify({ image_data, mime }) }),
  getMyPoints: (cursor?: string) =>
    apiFetch<{ items: PointTx[]; next_cursor?: string }>(`/me/points${cursor ? `?cursor=${cursor}` : ""}`),
  getMyTickets: () => apiFetch<QRPayload[]>(`/me/tickets`),

  // ★ PDPA มาตรา 30 — เจ้าของข้อมูลมีสิทธิขอสำเนาข้อมูลของตัวเอง
  //   backend มี endpoint นี้มาตั้งแต่แรกแต่ไม่เคยมีปุ่มไหนเรียก = มีสิทธิ์แต่ใช้ไม่ได้
  //   ตอบเป็น JSON เปล่าๆ ไม่มี Content-Disposition → ตั้งชื่อไฟล์เองฝั่งนี้
  exportMyData: () => downloadFile(`/me/export`, "egoke2026-my-data.json"),

  // attendance prompt (re-show ตอน login/reopen)
  getATPrompt: () => apiFetch<ATPrompt>(`/me/at-prompt`),
  dismissATPrompt: () => apiFetch<{ ok: boolean }>(`/me/at-prompt/dismiss`, { method: "POST" }),

  // votes
  listRounds: () => apiFetch<VoteRound[]>(`/vote-rounds`),
  castVote: (round_key: string, artist_id: string, idempotencyKey: string) =>
    apiFetch<VoteOut>(`/votes`, {
      method: "POST",
      body: JSON.stringify({ round_key, artist_id }),
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  getResults: (round_key: string) =>
    apiFetch<{ round_key: string; total_votes: number; results: ResultRow[]; is_final: boolean }>(
      `/vote-rounds/${round_key}/results`,
    ),

  // instagram — ★ ระบบจอใหญ่: จ่ายคะแนนก่อน แล้วส่งรูป + IG handle
  // ★ ราคามาจาก backend ไม่ hardcode ฝั่งเว็บ — ไม่งั้นวันไหนเปลี่ยนราคาจะโชว์คนละเลขกับที่หักจริง
  getIGConfig: () => apiFetch<IGConfig>(`/ig/config`),
  submitIG: (body: { image_data: string; instagram_handle: string; caption?: string }, idempotencyKey: string) =>
    apiFetch<{ id: string; status: string; queue_position: number; coins_spent: number; new_balance: number }>(`/ig/submissions`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  getMySubmissions: () => apiFetch<{ items: IGSubmission[] }>(`/me/submissions`),

  // wheel
  getWheel: (key: string) => apiFetch<WheelInfo>(`/wheel/${key}`),
  spinWheel: (key: string, client_seed: string, nonce: number, idempotencyKey: string) =>
    apiFetch<SpinOut>(`/wheel/${key}/spin`, {
      method: "POST",
      body: JSON.stringify({ client_seed, nonce }),
      headers: { "Idempotency-Key": idempotencyKey },
    }),

  // live (public, cached)
  getSnapshot: () => apiFetch<Snapshot>(`/live/snapshot`),

  // สถิติเช็คอินสด — staff ใช้ดูว่าประตูไหนแน่น และคนไหลเข้าเร็วแค่ไหน
  // อ่านจาก Redis ล้วน ไม่แตะ Mongo → poll ถี่ได้ไม่กระทบระบบ
  // (nginx ยัง cache ให้อีก 1 วิ ต่อให้ staff หลายสิบคนเปิดค้างไว้พร้อมกัน
  //  backend ก็เห็นแค่ ~1 request ต่อวินาที)
  getCheckinStats: () => apiFetch<CheckinStats>(`/live/checkin-stats`),

  // ig wall — สำหรับจอใหญ่ (ดึง approved submissions ที่มีรูป)
  // คืนเฉพาะใบที่ "ยังไม่เคยขึ้นจน" — ใบที่ฉายครบเวลาแล้วจะหายไปจากคิวถาวร
  getIGWall: (limit = 20) =>
    apiFetch<{ items: IGWallItem[]; as_of: string }>(`/live/ig-wall?limit=${limit}`),

  // จอแจ้งว่าฉายใบนี้ครบเวลาแล้ว → ตัดออกจากคิว
  // ★ ต้องมี DISPLAY_TOKEN เพราะ endpoint นี้เผาสิทธิ์ที่คนจ่ายเหรียญซื้อมา
  markIGWallShown: (id: string, token: string) =>
    apiFetch<{ ok: boolean; marked: boolean }>(
      `/live/ig-wall/${id}/shown?token=${encodeURIComponent(token)}`,
      { method: "POST" },
    ),

  // admin
  adminDashboard: () => apiFetch<AdminDashboard>(`/admin/dashboard`),
  adminUsers: (q = "", cursor?: string) =>
    apiFetch<{ users: AdminUserRow[]; next_cursor?: string }>(`/admin/users?q=${encodeURIComponent(q)}${cursor ? `&cursor=${cursor}` : ""}`),
  adminAdjustPoints: (id: string, amount: number, note: string, reason = "admin_adjust") =>
    apiFetch<{ transaction_id: string; new_balance: number }>(`/admin/users/${id}/points`, {
      method: "POST", body: JSON.stringify({ amount, note, reason }),
    }),
  // alias ที่ชัดเจนขึ้น — เปลี่ยนชื่อ service จาก points → coins แต้มยังใช้ endpoint เดิม (BC)
  adminAdjustCoins: (id: string, amount: number, note: string, reason = "admin_adjust") =>
    apiFetch<{ transaction_id: string; new_balance: number }>(`/admin/users/${id}/points`, {
      method: "POST", body: JSON.stringify({ amount, note, reason }),
    }),
  adminIGQueue: (status = "pending") =>
    apiFetch<{ items: AdminIGRow[]; total_pending: number }>(`/admin/ig/queue?status=${status}`),
  // อนุมัติ = ส่งมอบที่บนจอที่ผู้ใช้จ่ายเหรียญซื้อไว้แล้ว ไม่ได้จ่ายเหรียญเพิ่ม
  adminIGApprove: (id: string) =>
    apiFetch<{ ok: boolean; coins_awarded: number }>(`/admin/ig/${id}/approve`, { method: "POST" }),
  // ล้างคิวจอ — ทำเครื่องหมายทุกใบที่ค้างอยู่ว่าฉายจบแล้ว (ไม่ลบ ไม่คืนเหรียญ)
  adminClearIGWall: () =>
    apiFetch<{ ok: boolean; cleared: number }>(`/admin/ig/wall/clear`, { method: "POST" }),
  adminIGReject: (id: string, reason: string) =>
    apiFetch<{ ok: boolean; coins_refunded: number; new_balance: number }>(
      `/admin/ig/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: "POST" },
    ),
  // audit log — ประวัติทุก action ของ admin
  adminAuditLogs: (action?: string, cursor?: string, limit = 50) =>
    apiFetch<{ items: AuditLog[]; next_cursor?: string | null }>(
      `/admin/audit-logs?limit=${limit}${action ? `&action=${encodeURIComponent(action)}` : ""}${cursor ? `&cursor=${cursor}` : ""}`,
    ),
  adminAuditActions: () => apiFetch<{ actions: string[] }>(`/admin/audit-logs/actions`),
  adminPatchConfig: (body: ConfigPatch) =>
    apiFetch<{ ok: boolean; applied: Record<string, unknown> }>(`/admin/config`, { method: "PATCH", body: JSON.stringify(body) }),
  adminControlRound: (round_key: string, action: "open" | "close" | "publish") =>
    apiFetch(`/admin/vote-rounds/${round_key}/${action}`, { method: "POST" }),

  // admin attendees (เช็คชื่อจากรายชื่อ)
  adminAttendees: (q = "", event_day?: number, status?: string, cursor?: string) =>
    apiFetch<{ items: AttendeeRow[]; next_cursor?: string }>(
      `/admin/attendees?q=${encodeURIComponent(q)}${event_day ? `&event_day=${event_day}` : ""}${status ? `&status=${status}` : ""}${cursor ? `&cursor=${cursor}` : ""}`,
    ),
  adminManualCheckin: (user_id: string, event_day: number, gate = "ADMIN") =>
    apiFetch<CheckinOut>(`/admin/checkin/manual`, {
      method: "POST", body: JSON.stringify({ user_id, event_day, gate }),
    }),
  // ยกเลิกเช็คอินของวันนั้น — ใช้ตอน staff เลือกวันผิดแล้วสแกนไปแล้ว
  // ★ admin เท่านั้น — staff ถอนเช็คอินเองไม่ได้ ไม่งั้นร่องรอยว่าใครเข้างานจริงเชื่อไม่ได้
  adminUndoCheckin: (user_id: string, event_day: number) =>
    apiFetch<{ ok: boolean; checked_in_days: number[] }>(`/admin/checkin/undo`, {
      method: "POST", body: JSON.stringify({ user_id, event_day }),
    }),
  // เฝ้าดูการจ่ายเหรียญของ staff — ใช้จับความผิดปกติ
  adminGrantSummary: (hours = 24) =>
    apiFetch<GrantSummary>(`/admin/grants/summary?hours=${hours}`),
  adminResetGrantBudget: (staff_id: string) =>
    apiFetch<{ ok: boolean; cleared: number }>(`/admin/grants/reset-budget/${staff_id}`, {
      method: "POST",
    }),
  // ตั้งสิทธิ์ — ส่งชุดเต็ม ["staff"] / ["admin"] / [] (participant ระบบใส่ให้เอง)
  adminSetRoles: (user_id: string, roles: string[]) =>
    apiFetch<{ ok: boolean; roles: string[]; takes_effect: string }>(
      `/admin/users/${user_id}/roles`, { method: "POST", body: JSON.stringify({ roles }) },
    ),

  // staff — ชุดเดียวกับ admin แต่จำกัดสิทธิ์ (ไม่มี undo)
  staffAttendees: (q = "", event_day?: number, status?: string, cursor?: string) =>
    apiFetch<{ items: AttendeeRow[]; next_cursor?: string }>(
      `/staff/attendees?q=${encodeURIComponent(q)}${event_day ? `&event_day=${event_day}` : ""}${status ? `&status=${status}` : ""}${cursor ? `&cursor=${cursor}` : ""}`,
    ),
  staffManualCheckin: (user_id: string, event_day: number, gate = "STAFF") =>
    apiFetch<CheckinOut>(`/staff/checkin/manual`, {
      method: "POST", body: JSON.stringify({ user_id, event_day, gate }),
    }),
  // จ่ายเหรียญที่บูธ — เลือกจำนวนแล้วสแกน ไม่ผูกกับกิจกรรม
  // ★ ต้องส่ง Idempotency-Key เสมอ ไม่งั้นกดซ้ำตอนเน็ตช้า = จ่ายซ้ำ
  staffGrantCoins: (
    payload: string, amount: number, device_id: string, idempotencyKey: string, note = "",
  ) =>
    apiFetch<CoinGrantOut>(`/staff/coins/grant`, {
      method: "POST",
      body: JSON.stringify({ payload, amount, device_id, note }),
      headers: { "Idempotency-Key": idempotencyKey },
    }),

  // quests (บูธกิจกรรม)
  listQuests: () => apiFetch<Quest[]>(`/quests`),
  claimQuest: (quest_key: string, payload: string, device_id: string) =>
    apiFetch<QuestClaimOut>(`/quests/claim`, {
      method: "POST", body: JSON.stringify({ quest_key, payload, device_id }),
    }),
  adminListQuests: () => apiFetch<Quest[]>(`/admin/quests`),
  adminCreateQuest: (body: QuestInput) =>
    apiFetch<Quest>(`/admin/quests`, { method: "POST", body: JSON.stringify(body) }),
  adminUpdateQuest: (key: string, body: Partial<QuestInput>) =>
    apiFetch<Quest>(`/admin/quests/${key}`, { method: "PATCH", body: JSON.stringify(body) }),
  adminDeleteQuest: (key: string) =>
    apiFetch<{ ok: boolean; deleted: boolean; closed?: boolean; message?: string }>(
      `/admin/quests/${key}`, { method: "DELETE" },
    ),

  // checkin (staff)
  checkin: (body: CheckinBody, idempotencyKey: string) =>
    apiFetch<CheckinOut>(`/checkin`, { method: "POST", body: JSON.stringify(body), headers: { "Idempotency-Key": idempotencyKey } }),
  checkinBatch: (items: CheckinBody[]) =>
    apiFetch<{ results: { idempotency_key: string; result: string }[] }>(`/checkin/batch`, { method: "POST", body: JSON.stringify({ items }) }),
};

// ── types ─────────────────────────────────────────────────────────────
export interface User {
  id: string;
  email: string;
  display_name: string;
  // ★ ชื่อจริงจาก Google — สำคัญเมื่อเปิดรับอีเมลทุก domain
  //   อีเมลไม่ได้บอกว่าใครเป็นใครอีกต่อไป
  full_name?: string | null;
  avatar_url?: string;
  instagram_handle?: string;
  roles: string[];
  coins_balance: number;
  rank?: number;
  needs_onboarding?: boolean;
  faculty?: string;
  department?: string;
  student_id?: string;
}
export interface ProfileUpdate {
  display_name?: string;
  instagram_handle?: string;
  faculty?: string;
  department?: string;
  student_id?: string;
  consent_photo?: boolean;
}
export interface QRPayload {
  payload: string; ticket_code: string; event_day: number;
  status: string; checked_in_days: number[];
  rotating_code?: string | null; rotates_in?: number | null;
}
export interface VoteRound {
  round_key: string; title: string; status: string;
  opens_at?: string; closes_at?: string;
  results_public: boolean; max_votes_per_user: number;
  candidates: { id: string; name: string; image_url?: string; sort_order: number }[];
  my_vote?: string | null;
}
export interface VoteOut { accepted: boolean; round_key: string; artist_id: string; already_voted: boolean; results_visible: boolean; }
export interface ResultRow { artist_id: string; name: string; votes: number; percent: number; }
export interface IGSubmission {
  id: string; shortcode: string; status: string;
  // ★ ของ "ใบนี้" ไม่ใช่ของโปรไฟล์ — คนเดียวส่งหลายใบต้องเห็นต่างกัน
  instagram_handle?: string | null;
  caption?: string;
  coins_awarded: number;
  submitted_at: string;
  reviewed_at?: string | null;
  reject_reason?: string | null;
}
export interface IGConfig {
  cost_coins: number; image_max_bytes: number; caption_max: number; handle_pattern: string;
}
export interface AuditLog {
  id: string;
  action: string;
  actor: { id: string; display_name?: string | null; email?: string | null };
  target: { type?: string; id?: string };
  before?: unknown;
  after?: unknown;
  user_agent?: string;
  created_at: string;
}
export interface WheelInfo {
  wheel_key: string; title: string; cost_coins: number; status: string;
  segments: { id: string; label: string; prize_type: string; sold_out: boolean }[];
  commit_hash: string; my_spins_used: number; my_spins_left: number; my_coins: number;
}
export interface SpinOut {
  spin_id: string; result_segment_id: string; segment_index: number;
  label: string; prize_type: string; coins_won: number; coins_spent: number;
  coins_balance: number; proof: Record<string, unknown>;
}
export interface PointTx { id: string; amount: number; reason: string; note?: string; balance_after?: number; created_at: string; }
export interface Snapshot {
  server_time: string; seq: number;
  active_round?: { round_key: string; status: string; closes_in?: number; results_public: boolean; tally: { artist_id: string; name: string; votes: number }[] };
  checkins?: { today: number; total: number; rate_per_min: number };
  announcement?: { text: string; level: string };
  features?: Record<string, boolean>;
}
export interface CheckinStats {
  today: number;
  rate_per_min: number;
  /** นับแยกตามประตู — key คือชื่อประตูที่ staff ตั้งไว้ตอนสแกน */
  gates: Record<string, number>;
  /** 20 คนล่าสุด เรียงใหม่→เก่า (Redis list, ltrim ไว้ที่ 20) */
  // avatar_url เป็น null ได้ (คนที่ยังไม่ตั้งรูป) ไม่ใช่ undefined
  recent: { display_name: string; avatar_url?: string | null; gate: string; event_day: string; at: string }[];
  as_of: string;
}
export interface IGWallItem {
  id: string;
  // ★ backend ส่ง image_url (ลิงก์ /ig/image/{id} ที่ cache ได้) ไม่ใช่ base64 แล้ว
  //   จอ poll ทุก 10 วิ ถ้าแนบ base64 มาด้วยจะโหลดรูปทั้งกองใหม่ทุกครั้ง
  image_url?: string;
  image_data?: string;        // legacy — เผื่อ backend เวอร์ชันเก่า
  instagram_handle?: string;
  caption?: string;
  display_name?: string;
  shown_at?: string;
}
export interface AdminDashboard {
  users: { total: number; active: number };
  checkins: { today: number; total: number };
  votes: { total: number; stream_pending: number };
  ig: { pending: number; approved: number };
  spins: number;
  as_of: string;
}
export interface AdminUserRow {
  id: string; email: string; display_name?: string; student_id?: string;
  roles: string[]; status: string; coins_balance: number;
}
export interface AdminIGRow {
  id: string; shortcode: string; post_url: string; status: string;
  submitted_at: string; auto_flags: string[];
  // ★ ข้อมูลของใบที่ส่งมาจริง = สิ่งที่จะขึ้นจอถ้าอนุมัติ
  //   image_data เป็น data URL พร้อมใช้แล้ว (backend เติม prefix ให้)
  image_data?: string | null;
  caption?: string;
  instagram_handle?: string | null;
  user: { id: string; display_name?: string; instagram_handle?: string };
}
export interface ConfigPatch {
  maintenance_mode?: boolean;
  read_only_mode?: boolean;
  features?: Record<string, boolean>;
  announcement?: { text: string; level: "info" | "warn" | "error"; until?: string };
}
export interface CheckinBody {
  // ★ รับได้ 3 แบบ: QR payload เต็ม / รหัสบัตร EGOKE26-XXXX / รหัสนักศึกษา 7 หลัก
  payload: string; rotating_code?: string;
  event_day: number;        // 1/2/3 — staff เลือกที่เครื่องสแกน
  gate?: string;
  device_id: string; scanned_at?: string;
}
export type CheckinResult =
  | "ok" | "duplicate" | "invalid_sig" | "revoked" | "no_ticket"
  | "wrong_day" | "expired" | "rotating_code_mismatch" | "not_found"
  | "limit_reached"            // ★ โหมดจ่ายเหรียญเท่านั้น — บัตรปกติ แต่ชนโควตา
  | "queued" | "error";        // ★ 2 ตัวท้ายเกิดฝั่ง client เท่านั้น
export interface CheckinOut {
  result: CheckinResult;
  event_day?: number;
  matched_by?: string | null;   // "qr" | "ticket_code" | "student_id" | "manual"
  message?: string | null;      // ข้อความไทยจาก backend — โชว์ตรงๆ ได้เลย
  user?: { display_name?: string; full_name?: string | null; avatar_url?: string; student_id?: string };
  ticket?: { ticket_code?: string; event_day: number; tier: string; checked_in_days?: number[] };
  coins_awarded: number; checked_in_at?: string; checked_in_gate?: string;
}
export interface AttendeeRow {
  id: string; email: string; display_name?: string; full_name?: string | null; student_id?: string;
  faculty?: string; department?: string;
  ticket_code?: string; ticket_status?: string;
  checked_in_days: number[]; last_checked_in_at?: string;
  coins_balance: number;
}
export interface Quest {
  quest_key: string; title: string; description: string;
  coins: number; status: string; max_per_user: number; sort_order: number;
  my_claims: number;        // ผู้ใช้คนนี้รับไปแล้วกี่ครั้ง
  claimed_count: number;    // (admin) รวมทั้งงาน
}
export interface QuestInput {
  quest_key: string; title: string; description?: string;
  coins: number; status?: "open" | "closed"; max_per_user?: number; sort_order?: number;
}
export interface QuestClaimOut {
  result: "ok" | "duplicate" | "quest_closed" | "not_found" | "no_ticket" | "invalid_sig";
  message?: string | null;
  matched_by?: string | null;
  quest_key?: string | null;
  quest_title?: string | null;
  coins_awarded: number;
  user?: { display_name?: string; full_name?: string | null; avatar_url?: string; student_id?: string };
  claims_used: number;
  max_per_user: number;
}
/** ผลการจ่ายเหรียญที่บูธ — โครงเดียวกับ CheckinOut เพื่อใช้จอผลลัพธ์ร่วมกัน */
export interface CoinGrantOut {
  result: "ok" | "duplicate" | "limit_reached"
        | "not_found" | "no_ticket" | "invalid_sig" | "revoked" | "error";
  message?: string | null;
  matched_by?: string | null;
  coins_awarded: number;
  new_balance: number;
  user?: { display_name?: string; full_name?: string | null; avatar_url?: string; student_id?: string };
  // ชนโควตาอันไหน — staff ต้องรู้ว่าให้รอ ให้เปลี่ยนคน หรือให้ไปตาม admin
  limit_kind?: "per_scan" | "pair" | "receive" | "staff_daily" | null;
  limit_used?: number;
  limit_cap?: number;
  // ยอดที่ staff คนนี้จ่ายไปแล้ววันนี้ — โชว์บนเครื่องสแกนตลอดเวลา
  staff_used_today?: number;
  staff_cap_today?: number;
}

export interface GrantSummary {
  hours: number;
  summary: { coins: number; grants: number; receivers: number };
  by_staff: { id: string; name: string; coins: number; grants: number; people: number }[];
  by_user: { id: string; name: string; coins: number; grants: number; from_staff: number }[];
  pairs: { staff: string; user: string; user_id: string; coins: number; grants: number }[];
  limits: { per_scan: number; pair_daily: number; receive_daily: number; staff_daily: number };
}
export interface ATPrompt {
  show: boolean;
  event_day?: number;
  coins_awarded?: number;
  form_url?: string;
  checked_in_at?: string;
  dismissed?: boolean;
}
export interface CheckinNotifyPayload {
  type: "checkin_ok";
  event_day: number;
  coins_awarded: number;
  form_url: string;
  at: string;
}

// ── topup types (removed — staff เพิ่มcoinผ่าน /admin/users แทน) ──────
