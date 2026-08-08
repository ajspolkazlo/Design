"use client";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto max-w-sm pt-16 text-center">
      <p className="text-4xl">😵</p>
      <h1 className="mt-2 font-display text-xl font-bold">Something went wrong</h1>
      <p className="mt-1 text-sm text-muted">{error.message}</p>
      <button
        onClick={reset}
        className="mt-4 rounded-full bg-accent px-4 py-2 font-semibold text-white transition-colors duration-200 hover:bg-accent-orange dark:text-black"
      >
        Try again
      </button>
    </div>
  );
}
