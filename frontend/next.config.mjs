/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // ★ standalone = build ออกมาเป็น server.js + node_modules เท่าที่ใช้จริง
  //   ใช้ตอนใส่ Docker (Dockerfile) — ถ้าไม่มีบรรทัดนี้ต้อง copy node_modules
  //   ทั้งก้อนขึ้น image (หลายร้อย MB) ไม่มีผลกับ `next dev` / `next start` ปกติ
  output: "standalone",
  // รูป avatar มาจาก Google + Instagram CDN
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "lh3.googleusercontent.com" },
      { protocol: "https", hostname: "scontent-*.cdninstagram.com" },
      { protocol: "https", hostname: "instagram.f***.fbcdn.net" },
    ],
  },
  // API base สำหรับ fetch ฝั่ง server กับ client แยกกัน
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/v1",
  },
};

export default nextConfig;
