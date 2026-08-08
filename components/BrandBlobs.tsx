/**
 * Decorative bubble cluster for hero/login screens — the festival's actual
 * key visual is layered glossy spheres, not a soft AI-gradient blur. Solid
 * color, a light inner highlight for a balloon-like sheen, gently rotated
 * and overlapping. Purely decorative, no interactive role.
 */
const BUBBLES = [
  { size: 60, top: "-10%", left: "4%", color: "var(--color-accent-vivid)" },
  { size: 34, top: "12%", left: "28%", color: "var(--color-accent-yellow)" },
  { size: 46, top: "-6%", left: "58%", color: "var(--color-accent-sky)" },
  { size: 26, top: "30%", left: "84%", color: "var(--color-accent-orange)" },
  { size: 20, top: "58%", left: "14%", color: "var(--color-accent-mint)" },
  { size: 16, top: "50%", left: "72%", color: "var(--color-accent-purple)" },
];

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
          style={{
            width: b.size,
            height: b.size,
            top: b.top,
            left: b.left,
            background: b.color,
            boxShadow:
              "inset -8px -8px 14px rgba(0,0,0,0.12), inset 5px 6px 10px rgba(255,255,255,0.45)",
          }}
        />
      ))}
    </div>
  );
}
