/**
 * Splash-style hero panel modeled directly on BitterSweet's own app
 * screenshot: a hard-edged pink/purple color-block backdrop, oversized
 * glossy pearl bubbles bleeding off the edges, and a pixel-bitmap
 * wordmark — not a soft cream gradient.
 */
const BIG_BUBBLES = [
  { size: 92, top: "-22%", right: "-6%", color: "rgba(255,255,255,0.9)" },
  { size: 34, top: "34%", right: "10%", color: "rgba(255,255,255,0.75)" },
  { size: 30, top: "10%", left: "6%", color: "rgba(255,255,255,0.6)" },
  { size: 70, bottom: "-24%", left: "-8%", color: "rgba(255,255,255,0.85)" },
  { size: 22, bottom: "8%", left: "34%", color: "rgba(255,255,255,0.6)" },
];

function pearlStyle(size: number, color: string): React.CSSProperties {
  return {
    width: size,
    height: size,
    background: `radial-gradient(circle at 32% 26%, rgba(255,255,255,0.98) 0%, ${color} 22%, rgba(255,255,255,0.12) 60%, rgba(255,255,255,0.05) 100%)`,
    boxShadow: "inset -6px -10px 16px rgba(0,0,0,0.15), 0 4px 10px rgba(0,0,0,0.18)",
  };
}

export default function SplashHero() {
  return (
    <div className="relative mb-6 h-40 overflow-hidden rounded-3xl bg-accent-vivid">
      <div
        aria-hidden
        className="absolute -left-6 top-0 h-full w-2/3 -skew-x-12 bg-accent-purple opacity-90"
      />
      <div
        aria-hidden
        className="absolute -bottom-10 -right-10 h-2/3 w-1/2 rotate-12 bg-accent-blue-violet opacity-80"
      />
      {BIG_BUBBLES.map((b, i) => (
        <span
          key={i}
          aria-hidden
          className="absolute rounded-full"
          style={{
            top: b.top,
            left: b.left,
            right: b.right,
            bottom: b.bottom,
            ...pearlStyle(b.size, b.color),
          }}
        />
      ))}
      <div className="relative flex h-full flex-col items-center justify-center gap-1 text-center">
        <p className="font-display text-3xl leading-tight text-white">
          bitter
          <br />
          split
        </p>
        <p className="font-display text-[10px] tracking-[0.3em] text-white/80">
          EXPENSE SPLITTER
        </p>
      </div>
    </div>
  );
}
