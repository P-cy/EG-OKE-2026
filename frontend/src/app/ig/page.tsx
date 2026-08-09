"use client";

import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, newIdemKey } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { RetroCard } from "@/components/RetroCard";
import { NeonButton } from "@/components/NeonButton";
import { IGSubmissionRow } from "@/components/IGSubmissionRow";
import { toast } from "@/components/Toaster";
import { igLabel } from "@/lib/format";

// ราคาที่ใช้ตอนยังโหลด /ig/config ไม่เสร็จ — ค่าจริงมาจาก backend เสมอ
const FALLBACK_COST = 20;

// ★ ย่อรูปก่อนส่ง: ด้านยาวสุด 1440px, JPEG คุณภาพ 0.82
//   ของเดิมส่งไฟล์ดิบจากมือถือ (4–8MB) → เก็บ base64 ก้อนโตใน Mongo
//   → จอใหญ่ต้องโหลดทั้งกองทุกครั้งที่ poll และเน็ตหน้างานรับไม่ไหว
const MAX_EDGE = 1440;
const JPEG_QUALITY = 0.82;

export default function IGPage() {
  return (
    <ProtectedRoute>
      <IGContent />
    </ProtectedRoute>
  );
}

function IGContent() {
  const { user, refreshUser } = useAuth();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [imageData, setImageData] = useState<string>("");
  const [igHandle, setIgHandle] = useState(user?.instagram_handle || "");
  const [caption, setCaption] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [processing, setProcessing] = useState(false);

  const { data: cfg } = useQuery({
    queryKey: ["ig-config"],
    queryFn: () => api.getIGConfig(),
    staleTime: 5 * 60 * 1000,
  });
  const cost = cfg?.cost_coins ?? FALLBACK_COST;
  const captionMax = cfg?.caption_max ?? 200;

  const { data: subs } = useQuery({
    queryKey: ["my-submissions"],
    queryFn: () => api.getMySubmissions(),
    refetchInterval: 10000,
  });

  async function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      toast("ต้องเป็นไฟล์รูปเท่านั้น", "warn");
      return;
    }
    setProcessing(true);
    try {
      const { dataUrl, base64 } = await downscale(f, MAX_EDGE, JPEG_QUALITY);
      if (cfg && base64.length > cfg.image_max_bytes) {
        toast("รูปใหญ่เกินไปแม้ย่อแล้ว กรุณาเลือกรูปอื่น", "warn");
        return;
      }
      setPreview(dataUrl);
      setImageData(base64);
    } catch {
      toast("อ่านรูปไม่สำเร็จ กรุณาลองรูปอื่น", "error");
    } finally {
      setProcessing(false);
    }
  }

  async function submit() {
    if (!imageData) return toast("กรุณาเลือกรูปก่อน", "warn");
    const handle = igHandle.trim().replace(/^@/, "");
    if (!handle) return toast("กรุณาใส่ชื่อ IG ก่อน", "warn");
    if (!/^[A-Za-z0-9._]{1,30}$/.test(handle))
      return toast("ชื่อ IG ใช้ได้แค่ a-z 0-9 จุด และขีดล่าง", "warn");
    if ((user?.coins_balance ?? 0) < cost)
      return toast(`ต้องมีอย่างน้อย ${cost} coin`, "warn");

    setSubmitting(true);
    try {
      const res = await api.submitIG(
        { image_data: imageData, instagram_handle: handle, caption: caption.trim() || undefined },
        newIdemKey(),
      );
      toast(`ส่งสำเร็จ คิวที่ ${res.queue_position} — หัก ${res.coins_spent ?? cost} coin`, "success");
      setPreview(null);
      setImageData("");
      setCaption("");
      if (fileRef.current) fileRef.current.value = "";
      qc.invalidateQueries({ queryKey: ["my-submissions"] });
      qc.invalidateQueries({ queryKey: ["snapshot"] });
      // ยอดเหรียญเพิ่งถูกหัก — ดึงใหม่ ไม่งั้น header ยังโชว์ยอดเก่า
      refreshUser();
    } catch (e: any) {
      toast(e.message || "ส่งไม่สำเร็จ", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="font-mono text-2xl neon-text-pink tracking-widest">ส่งโพสต์ขึ้นจอใหญ่</h1>
        <p className="text-white/50 text-sm mt-1">
          จ่าย {cost} coin → แปะรูป + ชื่อ IG → รอ Admin อนุมัติ → ขึ้นจอหน้างาน
        </p>
      </div>

      <RetroCard glow="pink" title="ขั้นตอน">
        <ol className="text-sm text-white/70 space-y-1 list-decimal list-inside">
          <li>เลือกรูปจากเครื่อง (ระบบย่อขนาดให้อัตโนมัติ)</li>
          <li>ใส่ชื่อ IG ของคุณ (จะแสดงเป็น &quot;IG: @ชื่อ&quot;)</li>
          <li>กดส่ง → ระบบหัก {cost} coin → เข้าคิวรออนุมัติ</li>
          <li>Admin อนุมัติแล้วจะขึ้นจอใหญ่หน้างาน</li>
          <li>ถ้าถูกปฏิเสธ ระบบคืน {cost} coin ให้อัตโนมัติ</li>
        </ol>
      </RetroCard>

      <RetroCard glow="purple" title="ส่งรูปใหม่">
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-white/70 mb-2">รูปภาพ</label>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              onChange={onPickFile}
              className="block w-full text-sm text-white/60 file:mr-3 file:py-2 file:px-4 file:neon-border-blue file:bg-bg-deep file:text-neon-blue file:cursor-pointer"
            />
            {processing && <p className="text-xs text-neon-blue mt-2">กำลังย่อรูป...</p>}
            {preview && (
              <div className="mt-3 relative neon-border-pink p-2 inline-block">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={preview} alt="preview" className="max-h-60 rounded" />
                <p className="text-[10px] text-white/40 text-center mt-1">
                  ย่อแล้ว ~{Math.round((imageData.length * 3) / 4 / 1024)} KB
                </p>
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm text-white/70 mb-1">ชื่อ IG</label>
            <div className="flex items-center gap-2">
              <span className="font-mono text-neon-blue">IG: @</span>
              <input
                value={igHandle}
                onChange={(e) => setIgHandle(e.target.value)}
                className="flex-1 bg-bg-deep neon-border-blue px-3 py-2 text-white font-mono"
              />
            </div>
            {/* โชว์ตัวอย่างเฉพาะตอนพิมพ์แล้ว — ยังไม่พิมพ์ก็ไม่ต้องมีชื่อสมมติขึ้นมาให้งง */}
            {igHandle.trim() && (
              <p className="text-xs text-white/40 mt-1">
                จะแสดงบนจอเป็น: {igLabel(igHandle.trim().replace(/^@/, ""))}
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm text-white/70 mb-1">ข้อความ</label>
            <textarea
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              rows={2}
              maxLength={captionMax}
              className="w-full bg-bg-deep neon-border-blue px-3 py-2 text-white"
              placeholder="ข้อความที่จะแสดงใต้รูป"
            />
            <p className="text-xs text-white/30 text-right">{caption.length}/{captionMax}</p>
          </div>

          <div className="flex items-center justify-between pt-2 flex-wrap gap-2">
            <p className="text-sm">
              <span className="text-white/50">จะหัก </span>
              <span className="font-mono neon-text-pink">{cost} coin</span>
              <span className="text-white/50"> (คงเหลือ {user?.coins_balance ?? 0})</span>
            </p>
            <NeonButton variant="pink" loading={submitting} onClick={submit}>
              ส่งเข้าคิว
            </NeonButton>
          </div>
        </div>
      </RetroCard>

      <RetroCard glow="blue" title="สถานะคำขอของคุณ">
        {subs?.items?.length ? (
          <div className="space-y-3">
            {subs.items.map((s) => (
              <IGSubmissionRow key={s.id} sub={s} refundCoins={cost} />
            ))}
          </div>
        ) : (
          <p className="text-white/40 text-sm">ยังไม่เคยส่ง</p>
        )}
      </RetroCard>
    </div>
  );
}

/** ย่อรูปด้วย canvas → JPEG base64 (คืนทั้ง data URL สำหรับ preview และ base64 ล้วนสำหรับส่ง) */
function downscale(file: File, maxEdge: number, quality: number): Promise<{ dataUrl: string; base64: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("อ่านไฟล์ไม่ได้"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("รูปไม่ถูกต้อง"));
      img.onload = () => {
        const scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
        const w = Math.max(1, Math.round(img.width * scale));
        const h = Math.max(1, Math.round(img.height * scale));
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        if (!ctx) return reject(new Error("ไม่รองรับ canvas"));
        ctx.drawImage(img, 0, 0, w, h);
        const dataUrl = canvas.toDataURL("image/jpeg", quality);
        resolve({ dataUrl, base64: dataUrl.split(",")[1] || "" });
      };
      img.src = reader.result as string;
    };
    reader.readAsDataURL(file);
  });
}
