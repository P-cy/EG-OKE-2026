"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Spinner } from "@/components/Spinner";
import { igLabel } from "@/lib/format";

// จอ IG wall — แสดงทีละ 1 คน คนละ 45 วิ คั่นด้วยจอรอ 3 วิ
//
// ★ กติกาคือ "ขึ้นจอคนละหนึ่งรอบ" ไม่ใช่วนซ้ำ
//   ใบที่ฉายครบ 45 วิ จะถูกแจ้งกลับไปที่ backend แล้วตัดออกจากคิวถาวร
//   ของเดิมวนโชว์ใบเดิมไม่จบ ซึ่งทำให้คนที่เพิ่งจ่าย 20 เหรียญต้องรอนานขึ้น
//   เรื่อยๆ ตามจำนวนใบเก่าที่สะสม
//
// ★ ฉาย items[0] เสมอ ไม่ต้องเดิน index
//   เพราะใบที่ฉายจบจะหายออกจากผลลัพธ์ของ API เอง หัวคิวจึงเลื่อนมาเอง
//   (ของเดิมเดิน index แล้วพอ component ถูก mount ใหม่ index กลับไป 0
//    = ขึ้นใบแรกซ้ำ ไม่มีทางไปถึงใบถัดไป)
const SLIDE_SECONDS = 45;
const WAIT_SECONDS = 3;

export default function DisplayIGWallPage() {
  const qc = useQueryClient();

  // ★ token ของจอ — อ่านจาก URL: /display/ig?token=DISPLAY_TOKEN
  //   ต้องมี ไม่งั้นแจ้ง "ฉายจบแล้ว" ไม่ได้ = คิวไม่เดิน วนใบเดิมเหมือนเดิม
  const [token, setToken] = useState<string | null>(null);
  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token"));
  }, []);

  const [waiting, setWaiting] = useState(false);
  // ใบที่เพิ่งแจ้งไปว่าฉายจบ — ซ่อนทันทีระหว่างรอ refetch
  // ไม่งั้นช่วง 1-2 วิก่อนข้อมูลใหม่มาถึง จอจะเด้งกลับไปโชว์ใบเดิมแวบนึง
  const [doneIds, setDoneIds] = useState<string[]>([]);

  const phaseStart = useRef(Date.now());
  const stateRef = useRef({ waiting: false, id: "", token: null as string | null });

  const wall = useQuery({
    queryKey: ["ig-wall"],
    queryFn: () => api.getIGWall(30),
    refetchInterval: 10000,
    retry: 1,
  });

  const items = (wall.data?.items || []).filter((i) => !doneIds.includes(i.id));
  const item = items[0];
  const queueAhead = Math.max(0, items.length - 1);

  stateRef.current = { waiting, id: item?.id || "", token };

  // เริ่มจับเวลาใหม่ทุกครั้งที่ "ใบที่ฉาย" เปลี่ยน — ใบใหม่ต้องได้ 45 วิเต็มเสมอ
  // (เขียน ref ใน effect ไม่ใช่ตอน render — React ห้ามเขียน ref ระหว่าง render)
  useEffect(() => {
    if (item?.id) phaseStart.current = Date.now();
  }, [item?.id]);

  useEffect(() => {
    const tick = setInterval(async () => {
      const { waiting: w, id, token: tk } = stateRef.current;
      const elapsed = (Date.now() - phaseStart.current) / 1000;

      if (!w) {
        if (!id || elapsed < SLIDE_SECONDS) return;   // ยังฉายไม่ครบเวลา
        phaseStart.current = Date.now();
        setWaiting(true);
        setDoneIds((prev) => [...prev, id]);
        if (tk) {
          // ★ ยิงแล้วไม่รอผล — จอต้องเดินต่อแม้เน็ตสะดุด
          //   ถ้ายิงไม่สำเร็จ ใบนั้นจะกลับมาอยู่ในคิวรอบหน้า (เสียแค่ฉายซ้ำ
          //   ไม่ใช่เสียสิทธิ์ของคนจ่ายเงิน) — เลือกพังไปทางที่ปลอดภัยกว่า
          api.markIGWallShown(id, tk).catch(() => {});
        }
        return;
      }

      if (elapsed < WAIT_SECONDS) return;
      phaseStart.current = Date.now();
      setWaiting(false);
      qc.invalidateQueries({ queryKey: ["ig-wall"] });
    }, 250);
    return () => clearInterval(tick);
  }, [qc]);

  return (
    <div className="min-h-screen flex flex-col">
      <header className="text-center py-5">
        <h1 className="font-mono text-5xl neon-text-pink tracking-widest animate-flicker">
          IG WALL
        </h1>
        <p className="text-white/40 font-mono text-xl mt-1">EG&apos;OKE 2026</p>
      </header>

      {/* ★ ไม่มี token = แจ้ง "ฉายจบแล้ว" ไม่ได้ = คิวไม่เดิน วนใบเดิมตลอดงาน
          ต้องเห็นชัดจากหลังห้อง ไม่งั้นจะไปรู้ตัวตอนงานเริ่มไปแล้ว */}
      {token === null && !wall.isLoading && (
        <div className="mx-8 mb-4 border-2 border-neon-yellow bg-neon-yellow/10 px-6 py-3 text-center">
          <p className="font-mono text-2xl text-neon-yellow">เปิดจอผิดวิธี</p>
          <p className="text-white/70 text-lg mt-1">
            ต้องเปิดด้วย <span className="font-mono">/display/ig?token=&lt;DISPLAY_TOKEN&gt;</span>
            {" "}ไม่งั้นจอจะวนโพสต์เดิมไม่จบ
          </p>
        </div>
      )}

      <div className="flex-1 flex items-center justify-center px-8 pb-6">
        {wall.isLoading ? (
          <Spinner size={60} />
        ) : waiting ? (
          <div className="text-center animate-flicker">
            <p className="font-mono text-7xl neon-text-blue tracking-widest">EG&apos;OKE 2026</p>
            <p className="text-white/40 text-3xl mt-6">
              {queueAhead > 0 ? `รออีก ${queueAhead} โพสต์` : "รอโพสต์ถัดไป..."}
            </p>
          </div>
        ) : item ? (
          <div key={item.id} className="w-full max-w-5xl flex flex-col items-center animate-slide-in">
            {/* รูป — เล็กลงนิดเพื่อเปิดที่ให้ตัวหนังสือ */}
            <div className="w-full aspect-square max-w-[52vh] bg-bg-deep neon-border-pink rounded overflow-hidden flex items-center justify-center">
              {/* ★ image_url มาก่อน — เป็นลิงก์ที่ browser cache ได้
                  image_data เก็บไว้เผื่อ backend เวอร์ชันเก่าเท่านั้น */}
              {item.image_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={item.image_url} alt={item.instagram_handle || ""} className="w-full h-full object-cover" />
              ) : item.image_data ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={item.image_data.startsWith("http") || item.image_data.startsWith("data:")
                    ? item.image_data
                    : `data:image/jpeg;base64,${item.image_data}`}
                  alt={item.instagram_handle || ""}
                  className="w-full h-full object-cover"
                />
              ) : (
                <span className="text-9xl font-mono neon-text-pink">
                  {item.instagram_handle?.[0]?.toUpperCase() || "?"}
                </span>
              )}
            </div>

            {/* ★ ชื่อ IG — ตัวหลักของจอ ต้องอ่านออกจากท้ายห้อง */}
            <p className="font-mono text-6xl sm:text-7xl neon-text-blue mt-8 text-center break-all leading-tight">
              {igLabel(item.instagram_handle)}
            </p>

            {/* ★ แคปชัน — ใหญ่ขึ้นมาก จากเดิม text-xl */}
            {item.caption && (
              <p className="text-center text-white/85 text-3xl sm:text-4xl mt-6 max-w-4xl leading-snug">
                {item.caption}
              </p>
            )}

            {item.display_name && (
              <p className="text-center text-white/35 text-lg mt-4">{item.display_name}</p>
            )}
          </div>
        ) : (
          <div className="text-center text-white/40">
            <p className="text-4xl mb-4">ยังไม่มีโพสต์ขึ้นจอ</p>
            <p className="text-2xl">โพสต์ IG แล้วรอ admin อนุมัติ</p>
          </div>
        )}
      </div>
    </div>
  );
}
