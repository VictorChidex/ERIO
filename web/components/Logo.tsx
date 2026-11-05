// The ERIO mark: a globe open on the right whose latitude lines form an E,
// with a dot at the end of the middle line, the job you found. One drawing
// serves the header, footer, favicon, app icons and share image.

export const MARK = {
  viewBox: "0 0 112 112",
  ring: "M91.2 26.4 A46 46 0 1 0 91.2 85.6",
  bars: "M13.7 38 H70 M10 56 H60 M13.7 74 H70",
  dot: { cx: 79, cy: 56, r: 8 },
  stroke: 10,
};

// Fixed colors for images, which cannot follow the site theme.
export const BRAND = { navy: "#060a12", ring: "#4f7fff", bars: "#eaf1ff", dot: "#22d3ee" };

type MarkProps = {
  size: number;
  ring?: string;
  bars?: string;
  dot?: string;
  showDot?: boolean;
};

export function LogoMark({
  size,
  ring = "var(--logo-ring)",
  bars = "var(--logo-bars)",
  dot = "var(--logo-dot)",
  showDot = true,
}: MarkProps) {
  return (
    <svg width={size} height={size} viewBox={MARK.viewBox} aria-hidden="true" focusable="false">
      <path d={MARK.ring} fill="none" stroke={ring} strokeWidth={MARK.stroke} strokeLinecap="round" />
      <path d={MARK.bars} fill="none" stroke={bars} strokeWidth={MARK.stroke} strokeLinecap="round" />
      {showDot && <circle {...MARK.dot} fill={dot} />}
    </svg>
  );
}

// The mark beside the lowercase wordmark, as in the header and footer.
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      <span className="logo-word">erio</span>
    </span>
  );
}
