// จอ display ไม่มี nav ไม่มี header — เต็มจอ 16:9
export default function DisplayLayout({ children }: { children: React.ReactNode }) {
  return <div className="min-h-screen">{children}</div>;
}
