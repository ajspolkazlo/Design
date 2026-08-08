/**
 * Decorative gradient blobs (pink -> orange -> purple) for hero/empty/login
 * screens, evoking the bittersweet festival's balloon key visuals. Purely
 * decorative: absolutely positioned, behind content, no interactive role.
 */
export default function BrandBlobs() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-72 overflow-hidden"
    >
      <div className="brand-blob -left-16 -top-20 size-64" />
      <div className="brand-blob -right-20 top-8 size-56" />
    </div>
  );
}
