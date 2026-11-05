import { ImageResponse } from "next/og";

import { BRAND, LogoMark } from "@/components/Logo";

// The home-screen icon on iPhone and iPad: the mark on the navy tile.
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: BRAND.navy,
        }}
      >
        <LogoMark size={128} ring={BRAND.ring} bars={BRAND.bars} dot={BRAND.dot} />
      </div>
    ),
    size,
  );
}
