import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Job alerts",
  robots: { index: false, follow: false },
};

export default function AlertsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="wrap" style={{ padding: "56px 0 80px", maxWidth: 640 }}>
      {children}
    </div>
  );
}
