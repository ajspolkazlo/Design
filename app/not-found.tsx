import Link from "next/link";
import BrandBlobs from "@/components/BrandBlobs";

export default function NotFound() {
  return (
    <div className="relative mx-auto max-w-sm pt-10 text-center">
      <BrandBlobs />
      <p className="text-4xl">🔍</p>
      <h1 className="mt-2 text-xl font-semibold">Not found</h1>
      <p className="mt-1 text-sm text-muted">That page or group doesn&apos;t exist.</p>
      <Link
        href="/"
        className="mt-4 btn-flat bg-accent-vivid px-5 py-2.5 text-sm text-white"
      >
        Back home
      </Link>
    </div>
  );
}
