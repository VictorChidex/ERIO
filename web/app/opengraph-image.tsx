import { ImageResponse } from "next/og";

import { BRAND, LogoMark } from "@/components/Logo";

// The preview card when an ERIO link is shared (LinkedIn, X, WhatsApp, Slack).
export const alt = "ERIO — jobs in every country";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "0 110px",
          background: BRAND.navy,
          color: BRAND.bars,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 36 }}>
          <LogoMark size={190} ring={BRAND.ring} bars={BRAND.bars} dot={BRAND.dot} />
          <div style={{ fontSize: 150, fontWeight: 700, letterSpacing: -6 }}>erio</div>
        </div>
        <div style={{ marginTop: 48, fontSize: 56, color: "#7a9ec5" }}>
          Jobs in every country
        </div>
      </div>
    ),
    size,
  );
}
