import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { getCurrentUser } from "@/lib/session";
import { getGroupBalances } from "@/lib/balances";
import { formatCents, toGroupCents } from "@/lib/money";
import { categoryIcon, categoryLabel } from "@/lib/categories";
import { paletteColor } from "@/lib/palette";
import DeleteButton from "@/components/DeleteButton";
import BrandBlobs from "@/components/BrandBlobs";
import { deletePayment } from "@/app/actions";

export const dynamic = "force-dynamic";

export default async function GroupPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const me = await getCurrentUser();
  if (!me) redirect("/login");

  const { id } = await params;
  const { tab = "activity" } = await searchParams;

  const group = await prisma.group.findUnique({
    where: { id },
    include: {
      members: { include: { user: true } },
      expenses: {
        include: { payer: true, splits: { include: { user: true } } },
        orderBy: [{ date: "desc" }, { createdAt: "desc" }],
      },
      payments: {
        include: { from: true, to: true },
        orderBy: { date: "desc" },
      },
    },
  });
  if (!group) notFound();

  const userById = new Map(group.members.map((m) => [m.user.id, m.user]));
  const name = (userId: string) => {
    const u = userById.get(userId);
    if (!u) return "someone";
    return u.id === me.id ? "you" : u.name;
  };

  return (
    <div className="relative min-h-[70vh]">
      <BrandBlobs />

      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{group.name}</h1>
          <p className="text-sm text-muted">
            {group.members.map((m) => m.user.name).join(", ")} · {group.currency}
          </p>
        </div>
        <Link
          href={`/groups/${id}/members`}
          className="btn-flat shrink-0 border border-border px-3 py-2 text-xs text-foreground"
        >
          Members
        </Link>
      </div>

      {/* Underline tabs, as in the app — not a pill segmented control. */}
      <div className="mb-2 flex gap-6 border-b border-border">
        {[
          { id: "activity", label: "Activity" },
          { id: "balances", label: "Balances" },
        ].map((t) => (
          <Link
            key={t.id}
            href={`/groups/${id}?tab=${t.id}`}
            className={`-mb-px border-b-2 pb-2.5 text-sm font-semibold transition-colors ${
              tab === t.id
                ? "border-accent-vivid text-foreground"
                : "border-transparent text-muted hover:text-foreground"
            }`}
          >
            {t.label}
          </Link>
        ))}
      </div>

      {tab === "balances" ? (
        <BalancesTab group={group} meId={me.id} name={name} />
      ) : (
        <ActivityTab group={group} name={name} />
      )}

      {/* Action bar docked above the tab bar, on a solid ground so scrolling
          content passes behind it cleanly rather than peeking through. */}
      <div className="fixed inset-x-0 bottom-16 z-10 border-t border-border bg-background px-4 py-3">
        <Link
          href={`/groups/${id}/expenses/new`}
          className="btn-flat mx-auto w-full max-w-2xl bg-accent-vivid py-3.5 text-sm text-white"
        >
          + Add expense
        </Link>
      </div>
    </div>
  );
}

type GroupWithAll = NonNullable<
  Awaited<
    ReturnType<
      typeof prisma.group.findUnique<{
        where: { id: string };
        include: {
          members: { include: { user: true } };
          expenses: {
            include: { payer: true; splits: { include: { user: true } } };
          };
          payments: { include: { from: true; to: true } };
        };
      }>
    >
  >
>;

function ActivityTab({
  group,
  name,
}: {
  group: GroupWithAll;
  name: (id: string) => string;
}) {
  type Item =
    | { kind: "expense"; date: Date; expense: GroupWithAll["expenses"][number] }
    | { kind: "payment"; date: Date; payment: GroupWithAll["payments"][number] };

  const items: Item[] = [
    ...group.expenses.map((e) => ({ kind: "expense" as const, date: e.date, expense: e })),
    ...group.payments.map((p) => ({ kind: "payment" as const, date: p.date, payment: p })),
  ].sort((a, b) => b.date.getTime() - a.date.getTime());

  const dateFmt = new Intl.DateTimeFormat("en", { month: "short", day: "numeric" });

  if (items.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted">
        Nothing here yet — add the first expense.
      </p>
    );
  }

  return (
    <ul className="pb-40">
      {items.map((item) =>
        item.kind === "expense" ? (
          <li key={`e-${item.expense.id}`} className="border-b border-border">
            <Link
              href={`/groups/${group.id}/expenses/${item.expense.id}/edit`}
              className="flex items-center gap-3 py-4 transition-colors hover:text-accent"
            >
              <span
                className="cat-dot mt-1 size-2.5 shrink-0 self-start"
                style={{ background: paletteColor(item.expense.category) }}
                title={categoryLabel(item.expense.category)}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">
                  {item.expense.description}
                </span>
                <span className="block text-xs text-muted first-letter:uppercase">
                  {name(item.expense.payerId)} paid · split{" "}
                  {item.expense.splitType.toLowerCase()} between{" "}
                  {item.expense.splits.length}
                </span>
              </span>
              <span className="text-right">
                <span className="block font-semibold">
                  {formatCents(item.expense.amountCents, item.expense.currency)}
                </span>
                <span className="block text-xs text-muted">
                  {dateFmt.format(item.date)}
                </span>
              </span>
            </Link>
          </li>
        ) : (
          <li
            key={`p-${item.payment.id}`}
            className="flex items-center gap-3 border-b border-border py-4"
          >
            <span
              className="cat-dot mt-1 size-2.5 shrink-0 self-start bg-accent-green"
              aria-hidden
            />
            <span className="min-w-0 flex-1">
              <span className="block font-medium first-letter:uppercase">
                {name(item.payment.fromId)} paid {name(item.payment.toId)}
              </span>
              <span className="block text-xs text-muted">
                {item.payment.note ?? "settlement"} · {dateFmt.format(item.date)}
              </span>
            </span>
            <span className="font-semibold text-positive">
              {formatCents(item.payment.amountCents, item.payment.currency)}
            </span>
            <DeleteButton
              action={deletePayment.bind(null, item.payment.id)}
              label="✕"
              confirmText="Remove this settlement? Balances will update."
            />
          </li>
        )
      )}
    </ul>
  );
}

async function BalancesTab({
  group,
  meId,
  name,
}: {
  group: GroupWithAll;
  meId: string;
  name: (id: string) => string;
}) {
  const { net, transfers } = await getGroupBalances(group.id);

  const rows = group.members
    .map((m) => ({ user: m.user, cents: net.get(m.user.id) ?? 0 }))
    .sort((a, b) => b.cents - a.cents);

  // Spending by category, in group currency.
  const byCategory = new Map<string, number>();
  for (const e of group.expenses) {
    const cents = toGroupCents(e.amountCents, e.exchangeRate);
    byCategory.set(e.category, (byCategory.get(e.category) ?? 0) + cents);
  }
  const categories = [...byCategory.entries()].sort((a, b) => b[1] - a[1]);
  const maxCategory = categories[0]?.[1] ?? 0;
  const totalSpent = categories.reduce((acc, [, c]) => acc + c, 0);

  return (
    <div className="space-y-7 pb-40">
      <section>
        <h2 className="mb-1 text-sm font-semibold text-muted">Net balances</h2>
        <ul>
          {rows.map(({ user, cents }) => (
            <li
              key={user.id}
              className="flex items-center justify-between border-b border-border py-3.5"
            >
              <span className="font-medium">
                {user.emoji} {user.name}
                {user.id === meId && <span className="text-muted"> (you)</span>}
              </span>
              {cents === 0 ? (
                <span className="text-sm text-muted">settled</span>
              ) : (
                <span
                  className={`font-semibold ${cents > 0 ? "text-positive" : "text-negative"}`}
                >
                  {cents > 0 ? "gets back " : "owes "}
                  {formatCents(Math.abs(cents), group.currency)}
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="mb-1 text-sm font-semibold text-muted">
          Suggested settlements ({transfers.length}{" "}
          {transfers.length === 1 ? "payment" : "payments"})
        </h2>
        {transfers.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted">All settled up 🎉</p>
        ) : (
          <ul>
            {transfers.map((t) => (
              <li
                key={`${t.fromId}-${t.toId}`}
                className="flex items-center justify-between gap-3 border-b border-border py-3.5"
              >
                <span className="min-w-0 text-sm first-letter:uppercase">
                  <strong className="font-semibold">{name(t.fromId)}</strong> pays{" "}
                  <strong className="font-semibold">{name(t.toId)}</strong>{" "}
                  <span className="font-semibold">
                    {formatCents(t.amountCents, group.currency)}
                  </span>
                </span>
                <Link
                  href={`/groups/${group.id}/settle?from=${t.fromId}&to=${t.toId}&amount=${(t.amountCents / 100).toFixed(2)}`}
                  className="btn-flat shrink-0 bg-accent-blue-violet px-3 py-1.5 text-[11px] text-white"
                >
                  Settle
                </Link>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 text-right">
          <Link
            href={`/groups/${group.id}/settle`}
            className="text-sm font-semibold text-accent"
          >
            Record a custom payment →
          </Link>
        </div>
      </section>

      {categories.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-muted">
            Spending by category · {formatCents(totalSpent, group.currency)} total
          </h2>
          <div className="space-y-3">
            {categories.map(([cat, cents]) => (
              <div key={cat}>
                <div className="mb-1 flex items-baseline justify-between text-sm">
                  <span>
                    {categoryIcon(cat)} {categoryLabel(cat)}
                  </span>
                  <span className="font-semibold tabular-nums">
                    {formatCents(cents, group.currency)}
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden bg-border">
                  <div
                    className="h-full"
                    style={{
                      width: `${Math.max(2, (cents / maxCategory) * 100)}%`,
                      background: paletteColor(cat),
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="text-center">
        <a
          href={`/groups/${group.id}/export`}
          className="text-sm font-semibold text-accent"
        >
          ⬇ Export history as CSV
        </a>
      </section>
    </div>
  );
}
