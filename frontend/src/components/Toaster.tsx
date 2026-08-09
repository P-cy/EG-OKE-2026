"use client";

import { useEffect, useState } from "react";

type Toast = { id: number; msg: string; level: "info" | "warn" | "error" | "success" };

let push: ((t: Omit<Toast, "id">) => void) | null = null;

export function toast(msg: string, level: Toast["level"] = "info") {
  push?.({ msg, level });
}

export function Toaster() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    push = (t) => {
      const id = Date.now() + Math.random();
      setItems((s) => [...s, { ...t, id }]);
      setTimeout(() => setItems((s) => s.filter((x) => x.id !== id)), 3500);
    };
    return () => { push = null; };
  }, []);

  const colors: Record<Toast["level"], string> = {
    info: "neon-border-blue",
    success: "neon-border-pink",
    warn: "neon-border-pink",
    error: "neon-border-pink",
  };

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2">
      {items.map((t) => (
        <div
          key={t.id}
          className={`retro-panel scanlines ${colors[t.level]} px-4 py-3 min-w-[260px] max-w-sm`}
        >
          <p className="text-sm font-medium text-white">{t.msg}</p>
        </div>
      ))}
    </div>
  );
}
