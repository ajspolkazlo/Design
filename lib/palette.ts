/** Rotating secondary accents for tags, charts, and decorative chips. */
export const ROTATING_ACCENTS = [
  "var(--color-accent-orange)",
  "var(--color-accent-sky)",
  "var(--color-accent-purple)",
  "var(--color-accent-mint)",
  "var(--color-accent-yellow)",
  "var(--color-accent-blue-violet)",
] as const;

/** Deterministic color pick so the same category/group always gets the same accent. */
export function paletteColor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  return ROTATING_ACCENTS[hash % ROTATING_ACCENTS.length];
}
