import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // ต้องตรงกับ paths ใน tsconfig.json
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // เวลาเทสต์ต้องคงที่ ไม่งั้น assertion เรื่อง timezone จะเปลี่ยนตามเครื่องที่รัน
    env: { TZ: "Asia/Bangkok" },
  },
});
