import { describe, it, expect, vi, afterEach } from "vitest";
import {
  parseServerTime, formatDateTime, formatTime, relativeTime, formatCoins, countdown, igLabel,
} from "./format";

afterEach(() => vi.useRealTimers());

describe("parseServerTime", () => {
  it("ตีความเวลาที่ไม่มี timezone เป็น UTC", () => {
    // ★ นี่คือบั๊กจริงที่เจอ: motor คืน datetime แบบ naive → orjson ส่งสตริงไม่มี Z
    //   ถ้าปล่อยให้ new Date() จัดการ สเปก JS จะตีความเป็น "เวลาท้องถิ่น"
    //   ที่กรุงเทพฯ = เพี้ยนไป 7 ชม. ทุกที่ในเว็บ
    const naive = parseServerTime("2026-08-07T06:11:43.548000");
    expect(naive.toISOString()).toBe("2026-08-07T06:11:43.548Z");
  });

  it("ไม่ยุ่งกับเวลาที่มี timezone มาแล้ว", () => {
    expect(parseServerTime("2026-08-07T06:11:43.548000+00:00").toISOString())
      .toBe("2026-08-07T06:11:43.548Z");
    expect(parseServerTime("2026-08-07T13:11:43+07:00").toISOString())
      .toBe("2026-08-07T06:11:43.000Z");
    expect(parseServerTime("2026-08-07T06:11:43Z").toISOString())
      .toBe("2026-08-07T06:11:43.000Z");
  });

  it("naive กับ aware ของเวลาเดียวกันต้องได้ค่าเท่ากัน", () => {
    expect(parseServerTime("2026-08-07T06:11:43").getTime())
      .toBe(parseServerTime("2026-08-07T06:11:43+00:00").getTime());
  });

  it("สตริงพังหรือว่าง → Invalid Date ไม่ throw", () => {
    expect(Number.isNaN(parseServerTime("").getTime())).toBe(true);
    expect(Number.isNaN(parseServerTime("ไม่ใช่เวลา").getTime())).toBe(true);
  });
});

describe("formatDateTime / formatTime", () => {
  it("แสดงเป็นเวลาไทย (UTC+7) จากเวลา UTC ที่ไม่มี suffix", () => {
    // 06:11 UTC = 13:11 ที่กรุงเทพฯ
    expect(formatTime("2026-08-07T06:11:43.548000")).toContain("13:11");
    expect(formatDateTime("2026-08-07T06:11:43.548000")).toContain("13:11");
  });

  it("คืนสตริงเดิมถ้า parse ไม่ได้ — ไม่โชว์ 'Invalid Date' ให้ผู้ใช้เห็น", () => {
    expect(formatDateTime("พัง")).toBe("พัง");
    expect(formatTime("พัง")).toBe("พัง");
  });
});

describe("relativeTime", () => {
  it("เวลาที่เพิ่งผ่านไปต้องขึ้นว่าเมื่อสักครู่ ไม่ใช่ 7 ชม.ที่แล้ว", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-07T06:12:00Z"));
    // backend ส่งมาแบบ naive — ถ้า parse ผิดจะกลายเป็น "7 ชม.ที่แล้ว"
    expect(relativeTime("2026-08-07T06:11:43")).toBe("เมื่อสักครู่");
  });

  it("นับหน่วยถูกต้อง", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-07T12:00:00Z"));
    expect(relativeTime("2026-08-07T11:30:00Z")).toBe("30 นาทีที่แล้ว");
    expect(relativeTime("2026-08-07T09:00:00Z")).toBe("3 ชม.ที่แล้ว");
    expect(relativeTime("2026-08-05T12:00:00Z")).toBe("2 วันที่แล้ว");
  });

  it("สตริงพัง → คืนค่าว่าง ไม่ใช่ NaN", () => {
    expect(relativeTime("พัง")).toBe("");
  });
});

describe("formatCoins", () => {
  it("จัดรูปแบบตัวเลขและกันค่าว่าง", () => {
    expect(formatCoins(1234)).toBe("1,234");
    expect(formatCoins(0)).toBe("0");
    expect(formatCoins(null)).toBe("0");
    expect(formatCoins(undefined)).toBe("0");
    expect(formatCoins(NaN)).toBe("0");
  });
});

describe("countdown", () => {
  it("แสดงนาที:วินาที และหมดเวลา", () => {
    expect(countdown(0)).toBe("หมดเวลา");
    expect(countdown(-5)).toBe("หมดเวลา");
    expect(countdown(45)).toBe("45s");
    expect(countdown(90)).toBe("1:30");
    expect(countdown(605)).toBe("10:05");
  });
});

describe("igLabel", () => {
  it("เติม @ ให้ และไม่เติมซ้ำ", () => {
    expect(igLabel("pp_egoke")).toBe("IG: @pp_egoke");
    expect(igLabel("@pp_egoke")).toBe("IG: @pp_egoke");
  });

  it("ไม่มี handle → คืนค่าว่าง (ไม่โชว์ 'IG: @undefined')", () => {
    expect(igLabel("")).toBe("");
    expect(igLabel(null)).toBe("");
    expect(igLabel(undefined)).toBe("");
  });
});
