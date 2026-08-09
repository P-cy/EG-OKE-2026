"use client";

import { AttendeeCheckin } from "@/components/AttendeeCheckin";

// ตัวเดียวกับ /admin/attendees แต่ไม่มีปุ่มยกเลิกเช็คอิน
// (ProtectedRoute roles=["staff","admin"] ครอบมาจาก app/staff/layout.tsx แล้ว)
export default function StaffAttendeesPage() {
  return <AttendeeCheckin mode="staff" />;
}
