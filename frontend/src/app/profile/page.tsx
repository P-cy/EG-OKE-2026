"use client";

import { ProtectedRoute } from "@/components/ProtectedRoute";
import { ProfileCard } from "@/components/ProfileCard";

export default function ProfilePage() {
  return (
    <ProtectedRoute>
      <ProfileCard />
    </ProtectedRoute>
  );
}
