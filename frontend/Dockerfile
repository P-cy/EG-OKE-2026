# syntax=docker/dockerfile:1
# Image ของหน้าเว็บ — ใช้เมื่อรัน frontend บน VPS เครื่องเดียวกับ backend
# (ถ้าเอาไป deploy บน Vercel ไม่ต้องใช้ไฟล์นี้เลย)

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# ★ NEXT_PUBLIC_* ถูกฝังลงในไฟล์ JS ตอน build ไม่ใช่อ่านตอนรัน
#   เปลี่ยนโดเมน API = ต้อง build image ใหม่ ตั้งใน environment ของ container ไม่มีผล
#   (next.config.mjs ประกาศไว้ใน env: {} ยิ่งทำให้ค่าถูก inline ตั้งแต่ตอน build)
ARG NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
RUN test -n "$NEXT_PUBLIC_API_BASE" || \
      (echo "ERROR: ต้องส่ง --build-arg NEXT_PUBLIC_API_BASE=https://.../v1" && exit 1)

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0

# ★ ห้ามรันเป็น root
RUN addgroup -g 1001 nodejs && adduser -S -u 1001 -G nodejs nextjs

# output: "standalone" ใน next.config.mjs รวม dependency ที่ใช้จริงมาให้แล้ว
# → image เล็กกว่าการ copy node_modules ทั้งก้อนหลายเท่า
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
