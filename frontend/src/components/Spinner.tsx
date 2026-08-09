export function Spinner({ size = 40 }: { size?: number }) {
  return (
    <div
      className="inline-block animate-spin rounded-full"
      style={{
        width: size, height: size,
        border: "3px solid rgba(0, 229, 255, 0.2)",
        borderTopColor: "var(--neon-blue)",
        boxShadow: "0 0 10px var(--neon-blue)",
      }}
      aria-label="กำลังโหลด"
    />
  );
}
