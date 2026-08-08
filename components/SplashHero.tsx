/**
 * Splash panel modeled on the app's own launch screen: a hot-pink ground
 * with a stepped, pixelated purple block pattern, pale pearl bubbles
 * drifting over it, and the pixel-bitmap wordmark stacked in cream.
 */
const STEPS = [
  { x: 0, y: 3 },
  { x: 1, y: 3 },
  { x: 1, y: 2 },
  { x: 2, y: 2 },
  { x: 3, y: 2 },
  { x: 3, y: 1 },
  { x: 4, y: 1 },
  { x: 5, y: 1 },
  { x: 5, y: 0 },
  { x: 6, y: 0 },
  { x: 7, y: 0 },
];

const PEARLS = [
  { size: 84, top: "-16%", right: "-4%" },
  { size: 40, top: "44%", right: "14%" },
  { size: 30, top: "12%", left: "8%" },
  { size: 64, bottom: "-22%", left: "-6%" },
];

const CELL = 13; // % of panel width per pixel block

export default function SplashHero() {
  return (
    <div className="relative mb-6 h-44 overflow-hidden rounded-sm bg-accent-vivid">
      {STEPS.map((s, i) => (
        <span
          key={i}
          aria-hidden
          className="absolute bg-accent-blue-violet"
          style={{
            left: `${s.x * CELL}%`,
            top: `${s.y * 25}%`,
            width: `${CELL + 0.5}%`,
            height: "25.5%",
          }}
        />
      ))}

      {PEARLS.map((p, i) => (
        <span
          key={i}
          aria-hidden
          className="absolute rounded-full"
          style={{
            width: p.size,
            height: p.size,
            top: p.top,
            left: p.left,
            right: p.right,
            bottom: p.bottom,
            background:
              "radial-gradient(circle at 34% 27%, #ffffff 0%, #fff2f7 20%, rgba(255,214,229,0.75) 52%, rgba(255,190,214,0.45) 100%)",
            boxShadow: "inset -8px -12px 22px rgba(180,90,125,0.25)",
          }}
        />
      ))}

      <div className="relative flex h-full flex-col items-center justify-center">
        <p className="font-display text-2xl leading-[1.15] text-[#fdf2ec]">
          bitter
          <br />
          split
        </p>
        <p className="mt-2 font-display text-[9px] tracking-[0.35em] text-[#fdf2ec]/85">
          EXPENSES
        </p>
      </div>
    </div>
  );
}
