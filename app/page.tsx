import Link from "next/link";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/session";
import { getOverallBalances } from "@/lib/balances";
import { formatCents } from "@/lib/money";
import { paletteColor } from "@/lib/palette";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const me = await getCurrentUser();
  if (!me) redirect("/login");

  const { perGroup, totals } = await getOverallBalances(me.id);

  return (
    <div>
      <div className="mb-6 rounded-2xl border border-border bg-card p-5 shadow-sm">
        <h1 className="text-sm font-semibold text-muted">Overall, across all groups</h1>
        {totals.length === 0 || totals.every((t) => t.netCents === 0) ? (
          <p className="mt-1 text-2xl font-bold">You&apos;re all settled up 🎉</p>
        ) : (
          <div className="mt-1 space-y-0.5">
            {totals
              .filter((t) => t.netCents !== 0)
              .map((t) => (
                <p
                  key={t.currency}
                  className={`text-2xl font-bold ${t.netCents > 0 ? "text-positive" : "text-negative"}`}
                >
                  {t.netCents > 0 ? "you are owed " : "you owe "}
                  {formatCents(Math.abs(t.netCents), t.currency)}
                </p>
              ))}
          </div>
        )}
      </div>

      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-display text-lg font-bold">Your groups</h2>
        <Link
          href="/groups/new"
          className="pop rounded-full bg-accent px-4 py-2 text-sm font-semibold text-white transition-colors duration-200 hover:bg-accent-orange dark:text-black"
        >
          + New group
        </Link>
      </div>

      <div className="space-y-3">
        {perGroup.map((g) => (
          <Link
            key={g.groupId}
            href={`/groups/${g.groupId}`}
            className="flex items-center justify-between rounded-2xl border border-border bg-card p-4 shadow-sm transition-colors duration-200 hover:border-accent"
            style={{ borderTop: `4px solid ${paletteColor(g.groupId)}` }}
          >
            <span className="font-semibold">{g.groupName}</span>
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
          </Link>
        ))}
        {perGroup.length === 0 && (
          <p className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted">
            No groups yet. Create one to start splitting expenses.
          </p>
        )}
      </div>
    </div>
  );
}
