"use client";

import BrandBlobs from "@/components/BrandBlobs";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="relative mx-auto max-w-sm pt-10 text-center">
      <BrandBlobs />
      <p className="text-4xl">😵</p>
      <h1 className="mt-2 text-xl font-semibold">Something went wrong</h1>
      <p className="mt-1 text-sm text-muted">{error.message}</p>
      <button
        onClick={reset}
        className="mt-4 btn-flat bg-accent-vivid px-5 py-2.5 text-sm text-white"
      >
        Try again
      </button>
    </div>
  );
}
