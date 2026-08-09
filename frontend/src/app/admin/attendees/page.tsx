"use client";

import { AttendeeCheckin } from "@/components/AttendeeCheckin";

// เนื้อหาทั้งหมดอยู่ใน <AttendeeCheckin> เพราะ /staff/attendees ใช้ตัวเดียวกัน
// (ProtectedRoute roles=["admin"] ครอบมาจาก app/admin/layout.tsx แล้ว)
export default function AdminAttendeesPage() {
  return <AttendeeCheckin mode="admin" />;
}
