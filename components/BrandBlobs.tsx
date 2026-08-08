/**
 * Decorative bubble cluster matching the festival's actual key visual:
 * glossy, translucent pearl spheres with a bright specular highlight and a
 * soft shadowed underside, not flat circles or a blurred gradient.
 */
const BUBBLES = [
  { size: 60, top: "-10%", left: "4%", color: "var(--color-accent-vivid)" },
  { size: 34, top: "12%", left: "28%", color: "var(--color-accent-yellow)" },
  { size: 46, top: "-6%", left: "58%", color: "var(--color-accent-sky)" },
  { size: 26, top: "30%", left: "84%", color: "var(--color-accent-orange)" },
  { size: 20, top: "58%", left: "14%", color: "var(--color-accent-mint)" },
  { size: 16, top: "50%", left: "72%", color: "var(--color-accent-purple)" },
];

function bubbleStyle(color: string, size: number): React.CSSProperties {
  return {
    width: size,
    height: size,
    background: `radial-gradient(circle at 32% 26%, rgba(255,255,255,0.95) 0%, rgba(255,255,255,0.35) 16%, ${color} 48%, color-mix(in srgb, ${color} 55%, black) 100%)`,
    boxShadow: "inset -4px -8px 12px rgba(0,0,0,0.2), 0 3px 8px rgba(0,0,0,0.15)",
  };
}

/** Fixed-height bubble strip. Callers should reserve matching top clearance
 * (e.g. pt-28) so headline text sits below it rather than behind it. */
export default function BrandBlobs() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-24 overflow-hidden"
    >
      {BUBBLES.map((b, i) => (
        <span
          key={i}
          className="absolute rounded-full"
          style={{ top: b.top, left: b.left, ...bubbleStyle(b.color, b.size) }}
        />
      ))}
    </div>
  );
}
