import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-sm pt-16 text-center">
      <p className="text-4xl">🔍</p>
      <h1 className="mt-2 font-display text-xl font-bold">Not found</h1>
      <p className="mt-1 text-sm text-muted">That page or group doesn&apos;t exist.</p>
      <Link
        href="/"
        className="mt-4 inline-block rounded-full bg-accent px-4 py-2 font-semibold text-white transition-colors duration-200 hover:bg-accent-orange dark:text-black"
      >
        Back home
      </Link>
    </div>
  );
}
