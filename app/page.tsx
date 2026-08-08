import Link from "next/link";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/session";
import { getOverallBalances } from "@/lib/balances";
import { formatCents } from "@/lib/money";
import { paletteColor } from "@/lib/palette";
import BrandBlobs from "@/components/BrandBlobs";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const me = await getCurrentUser();
  if (!me) redirect("/login");

  const { perGroup, totals } = await getOverallBalances(me.id);

  return (
    <div className="relative min-h-[70vh]">
      <BrandBlobs />

      <section className="mb-8">
        <h1 className="text-sm font-semibold text-muted">
          Overall, across all groups
        </h1>
        {totals.length === 0 || totals.every((t) => t.netCents === 0) ? (
          <p className="mt-1 text-3xl font-semibold">You&apos;re all settled up 🎉</p>
        ) : (
          <div className="mt-1 space-y-0.5">
            {totals
              .filter((t) => t.netCents !== 0)
              .map((t) => (
                <p
                  key={t.currency}
                  className={`text-3xl font-semibold ${t.netCents > 0 ? "text-positive" : "text-negative"}`}
                >
                  {t.netCents > 0 ? "you are owed " : "you owe "}
                  {formatCents(Math.abs(t.netCents), t.currency)}
                </p>
              ))}
          </div>
        )}
      </section>

      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Your groups</h2>
        <Link
          href="/groups/new"
          className="btn-flat bg-accent-blue-violet px-3.5 py-2 text-xs text-white"
        >
          + New group
        </Link>
      </div>

      <ul>
        {perGroup.map((g) => (
          <li key={g.groupId} className="border-b border-border">
            <Link
              href={`/groups/${g.groupId}`}
              className="flex items-center gap-3 py-4 transition-colors hover:text-accent"
            >
              <span
                className="cat-dot size-2.5 shrink-0"
                style={{ background: paletteColor(g.groupId) }}
                aria-hidden
              />
              <span className="min-w-0 flex-1 truncate font-medium">
                {g.groupName}
              </span>
              {g.netCents === 0 ? (
                <span className="text-sm text-muted">settled up</span>
              ) : (
                <span
                  className={`text-sm font-semibold ${g.netCents > 0 ? "text-positive" : "text-negative"}`}
                >
                  {g.netCents > 0 ? "+" : "−"}
                  {formatCents(Math.abs(g.netCents), g.currency)}
                </span>
              )}
              <span aria-hidden className="text-muted">
                ›
              </span>
            </Link>
          </li>
        ))}
        {perGroup.length === 0 && (
          <li className="py-10 text-center text-sm text-muted">
            No groups yet. Create one to start splitting expenses.
          </li>
        )}
      </ul>
    </div>
  );
}
