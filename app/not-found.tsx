import Link from "next/link";
import BrandBlobs from "@/components/BrandBlobs";

export default function NotFound() {
  return (
    <div className="relative mx-auto max-w-sm pt-28 text-center">
      <BrandBlobs />
      <p className="text-4xl">🔍</p>
      <h1 className="mt-2 font-display text-xl font-bold">Not found</h1>
      <p className="mt-1 text-sm text-muted">That page or group doesn&apos;t exist.</p>
      <Link
        href="/"
        className="mt-4 inline-block pop rounded-full bg-accent px-4 py-2 font-semibold text-white transition-colors duration-200 hover:bg-accent-orange dark:text-black"
      >
        Back home
      </Link>
    </div>
  );
}
