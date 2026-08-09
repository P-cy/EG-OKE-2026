"use client";

import { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "pink" | "blue" | "purple" | "ghost" | "danger";

const styles: Record<Variant, string> = {
  pink: "neon-border-pink text-neon-pink hover:bg-neon-pink/10",
  blue: "neon-border-blue text-neon-blue hover:bg-neon-blue/10",
  purple: "neon-border-purple text-neon-purple hover:bg-neon-purple/10",
  ghost: "border border-white/20 text-white/70 hover:bg-white/5",
  danger: "border-2 border-red-500 text-red-400 hover:bg-red-500/10",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  children: ReactNode;
}

export function NeonButton({ variant = "pink", loading, children, className = "", disabled, ...rest }: Props) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={`retro-panel scanlines font-bold tracking-wide transition-all px-6 py-3 ${styles[variant]} ${
        disabled ? "opacity-40 cursor-not-allowed" : "hover:scale-[1.02] active:scale-95"
      } ${className}`}
    >
      {loading ? <span className="animate-pulse">กำลังประมวลผล...</span> : children}
    </button>
  );
}
