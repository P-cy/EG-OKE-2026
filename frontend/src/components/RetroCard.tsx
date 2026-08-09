import { HTMLAttributes, ReactNode } from "react";

interface Props extends HTMLAttributes<HTMLDivElement> {
  glow?: "pink" | "blue" | "purple" | "green" | "none";
  title?: string;
  children: ReactNode;
}

const glows = {
  pink: "neon-border-pink",
  blue: "neon-border-blue",
  purple: "neon-border-purple",
  green: "neon-border-green",
  none: "border border-white/10",
};

export function RetroCard({ glow = "blue", title, children, className = "", ...rest }: Props) {
  return (
    <div {...rest} className={`retro-panel scanlines rounded-md p-5 ${glows[glow]} ${className}`}>
      {title && (
        <h3 className="font-mono text-lg neon-text-pink mb-3 tracking-wider">{title}</h3>
      )}
      {children}
    </div>
  );
}
