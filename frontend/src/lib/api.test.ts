import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { newIdemKey, apiFetch, setToken, ApiError } from "./api";

const BASE = "http://localhost:8000/v1";

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** header ของ fetch call ที่ n — ดึงออกมาแบบ type-safe */
function headersOfCall(mock: { mock: { calls: any[][] } }, n = 0): Headers {
  return mock.mock.calls[n][1].headers as Headers;
}

function asApiError(e: unknown): ApiError {
  if (!(e instanceof ApiError)) throw new Error(`ต้องเป็น ApiError แต่ได้ ${String(e)}`);
  return e;
}

beforeEach(() => {
  setToken(null);
  vi.restoreAllMocks();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("newIdemKey", () => {
  it("คืน UUID เมื่อเบราว์เซอร์รองรับ", () => {
    expect(newIdemKey()).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("★ ยังทำงานได้เมื่อไม่มี crypto.randomUUID (เปิดเว็บผ่าน http:// บนมือถือ)", () => {
    // นี่คือสภาพจริงตอนทดสอบหน้างาน: เปิด http://192.168.x.x บนมือถือ
    // = ไม่ใช่ secure context → crypto.randomUUID เป็น undefined
    // ถ้าโค้ดเรียกตรงๆ จะ TypeError แล้ว "ทุกปุ่มที่เขียนข้อมูล" พังทั้งเว็บ
    vi.stubGlobal("crypto", { getRandomValues: crypto.getRandomValues.bind(crypto) });
    const k = newIdemKey();
    expect(k).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("ยังทำงานได้แม้ไม่มี crypto เลย", () => {
    vi.stubGlobal("crypto", undefined);
    expect(newIdemKey().length).toBeGreaterThan(10);
  });

  it("ไม่ซ้ำกันเอง", () => {
    const keys = new Set(Array.from({ length: 500 }, () => newIdemKey()));
    expect(keys.size).toBe(500);
  });
});

describe("apiFetch", () => {
  it("แนบ Idempotency-Key ให้ทุก request ที่เขียนข้อมูล", async () => {
    // สร้าง Response ใหม่ทุกครั้ง — body ของ Response อ่านได้ครั้งเดียว
    const fetchMock = vi.fn(async () => jsonRes({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      fetchMock.mockClear();
      await apiFetch("/x", { method });
      expect(headersOfCall(fetchMock).get("Idempotency-Key"), method).toBeTruthy();
    }
  });

  it("ไม่แนบ Idempotency-Key ให้ GET", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/x");
    expect(headersOfCall(fetchMock).get("Idempotency-Key")).toBeNull();
  });

  it("ใช้ Idempotency-Key ที่ส่งมาเอง ไม่สุ่มทับ", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/x", { method: "POST", headers: { "Idempotency-Key": "fixed-key" } });
    expect(headersOfCall(fetchMock).get("Idempotency-Key")).toBe("fixed-key");
  });

  it("แนบ Authorization เมื่อมี token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    setToken("tok123");
    await apiFetch("/me");
    expect(headersOfCall(fetchMock).get("Authorization")).toBe("Bearer tok123");
  });

  it("★ อ่าน error envelope ของ backend ออกมาเป็น code ที่ถูกต้อง", async () => {
    // ถ้า backend ตอบไม่ตรง envelope นี้ frontend จะได้ code = "UNKNOWN"
    // ซึ่งเป็นอาการที่เคยเจอหน้างานตอนสแกนเช็คอิน
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes({
      error: { code: "VALIDATION_ERROR", message: "ข้อมูลไม่ถูกต้อง", request_id: "abc" },
    }, 422)));

    const err = asApiError(await apiFetch("/checkin", { method: "POST" }).catch((e) => e));
    expect(err.code).toBe("VALIDATION_ERROR");
    expect(err.message).toBe("ข้อมูลไม่ถูกต้อง");
    expect(err.status).toBe(422);
    expect(err.requestId).toBe("abc");
  });

  it("body ที่ไม่ใช่ JSON → ยังโยน ApiError ไม่ค้าง", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response("<html>502</html>", { status: 502 }),
    ));
    const err = asApiError(await apiFetch("/x").catch((e) => e));
    expect(err.status).toBe(502);
    expect(err.code).toBe("UNKNOWN");
  });

  it("401 → refresh token แล้วยิงซ้ำครั้งเดียวด้วย token ใหม่", async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      calls.push(url);
      if (url.endsWith("/auth/refresh")) return jsonRes({ access_token: "new-tok" });
      if (calls.filter((c) => c.endsWith("/me")).length === 1) return jsonRes({}, 401);
      return jsonRes({ id: "u1" });
    });
    vi.stubGlobal("fetch", fetchMock);
    setToken("old-tok");

    const out = await apiFetch<{ id: string }>("/me");
    expect(out).toEqual({ id: "u1" });
    expect(calls).toEqual([`${BASE}/me`, `${BASE}/auth/refresh`, `${BASE}/me`]);
    expect(localStorage.getItem("access_token")).toBe("new-tok");
  });

  it("204 → คืน undefined ไม่พยายาม parse JSON ของว่าง", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(apiFetch("/x", { method: "DELETE" })).resolves.toBeUndefined();
  });
});
