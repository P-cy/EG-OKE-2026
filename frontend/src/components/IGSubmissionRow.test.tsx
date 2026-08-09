import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { IGSubmissionRow, IGStatusBadge } from "./IGSubmissionRow";
import type { IGSubmission } from "@/lib/api";

function sub(over: Partial<IGSubmission> = {}): IGSubmission {
  return {
    id: "1", shortcode: "local:abc", status: "pending",
    instagram_handle: "first_user", caption: "แคปชันของใบแรก",
    coins_awarded: 0, submitted_at: new Date().toISOString(),
    ...over,
  };
}

describe("IGSubmissionRow", () => {
  it("★ แต่ละแถวโชว์ชื่อ IG ของใบตัวเอง ไม่ใช่ค่าเดียวกันทุกแถว", () => {
    // บั๊กเดิม: หน้า /ig ดึงชื่อจาก state ของช่องกรอก → ทุกแถวขึ้นชื่อเดียวกัน
    // และเปลี่ยนไปเรื่อยๆ ตามที่ผู้ใช้กำลังพิมพ์
    render(
      <>
        <IGSubmissionRow sub={sub({ id: "1", instagram_handle: "first_user" })} />
        <IGSubmissionRow sub={sub({ id: "2", instagram_handle: "second_user" })} />
      </>,
    );
    expect(screen.getByText("IG: @first_user")).toBeInTheDocument();
    expect(screen.getByText("IG: @second_user")).toBeInTheDocument();
  });

  it("โชว์แคปชันของใบนั้น", () => {
    render(<IGSubmissionRow sub={sub({ caption: "ข้อความเฉพาะใบนี้" })} />);
    expect(screen.getByText("ข้อความเฉพาะใบนี้")).toBeInTheDocument();
  });

  it("ไม่มีชื่อ IG → บอกให้ชัด ไม่ปล่อยว่างเปล่า", () => {
    render(<IGSubmissionRow sub={sub({ instagram_handle: null })} />);
    expect(screen.getByText("(ไม่ระบุชื่อ IG)")).toBeInTheDocument();
  });

  it("ถูกปฏิเสธ → บอกเหตุผลและบอกว่าคืนเหรียญแล้ว", () => {
    render(
      <IGSubmissionRow
        sub={sub({ status: "rejected", reject_reason: "รูปไม่เหมาะสม" })}
        refundCoins={20}
      />,
    );
    expect(screen.getByText(/รูปไม่เหมาะสม/)).toBeInTheDocument();
    expect(screen.getByText(/คืน 20 coin/)).toBeInTheDocument();
  });

  it("ถูกปฏิเสธแบบไม่ระบุเหตุผล → ยังต้องมีข้อความ ไม่ปล่อยว่าง", () => {
    render(<IGSubmissionRow sub={sub({ status: "rejected", reject_reason: null })} />);
    expect(screen.getByText(/ไม่ระบุ/)).toBeInTheDocument();
  });

  it("สถานะอื่นไม่โชว์บรรทัดเหตุผล", () => {
    render(<IGSubmissionRow sub={sub({ status: "approved" })} />);
    expect(screen.queryByText(/เหตุผล:/)).not.toBeInTheDocument();
  });
});

describe("IGStatusBadge", () => {
  it("แปลสถานะเป็นภาษาไทยครบทุกตัวที่ backend ส่งได้", () => {
    const cases: [string, string][] = [
      ["pending", "รอตรวจ"],
      ["approved", "อนุมัติแล้ว"],
      ["rejected", "ปฏิเสธ"],
      ["flagged", "ตั้งข้อสังเกต"],
    ];
    for (const [status, thai] of cases) {
      const { unmount } = render(<IGStatusBadge status={status} />);
      expect(screen.getByText(thai)).toBeInTheDocument();
      unmount();
    }
  });

  it("สถานะที่ไม่รู้จัก → โชว์ค่าดิบ ไม่ใช่ช่องว่าง", () => {
    render(<IGStatusBadge status="weird_new_status" />);
    expect(screen.getByText("weird_new_status")).toBeInTheDocument();
  });
});
