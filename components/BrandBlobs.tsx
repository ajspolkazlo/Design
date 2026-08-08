/**
 * Large pearl-bubble watermark. The real app parks big, soft, pale-pink
 * pearls low behind the content of long screens rather than scattering
 * small bright dots at the top — they read as a faint background texture,
 * never competing with the text above them.
 */
const PEARLS = [
  { size: 300, bottom: -110, left: -70, opacity: 0.5 },
  { size: 380, bottom: -160, left: 120, opacity: 0.42 },
  { size: 220, bottom: -80, right: -60, opacity: 0.45 },
];

function pearl(size: number, opacity: number): React.CSSProperties {
  return {
    width: size,
    height: size,
    opacity,
    background: `radial-gradient(circle at 36% 28%, #ffffff 0%, #fff0f5 18%, #ffd9e6 42%, #ffc2d6 66%, #ffb3cd 100%)`,
    boxShadow: "inset -18px -26px 46px rgba(214,120,155,0.28)",
  };
}

export default function BrandBlobs() {
  return (
    <div
      aria-hidden
      className="pearl-field pointer-events-none fixed inset-x-0 bottom-0 -z-10 h-80 overflow-hidden"
    >
      {PEARLS.map((p, i) => (
        <span
          key={i}
          className="absolute rounded-full"
          style={{
            bottom: p.bottom,
            left: p.left,
            right: p.right,
            ...pearl(p.size, p.opacity),
          }}
        />
      ))}
    </div>
  );
}
