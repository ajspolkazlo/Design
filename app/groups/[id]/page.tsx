import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { getCurrentUser } from "@/lib/session";
import { getGroupBalances } from "@/lib/balances";
import { formatCents, toGroupCents } from "@/lib/money";
import { categoryIcon, categoryLabel } from "@/lib/categories";
import DeleteButton from "@/components/DeleteButton";
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
    <div>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold">{group.name}</h1>
          <p className="text-sm text-muted">
            {group.members.map((m) => m.user.name).join(", ")} · {group.currency}
          </p>
        </div>
        <Link
          href={`/groups/${id}/members`}
          className="shrink-0 rounded-xl border border-border bg-card px-3 py-2 text-sm font-semibold"
        >
          👥 Members
        </Link>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-1 rounded-xl border border-border bg-card p-1">
        {[
          { id: "activity", label: "Activity" },
          { id: "balances", label: "Balances" },
        ].map((t) => (
          <Link
            key={t.id}
            href={`/groups/${id}?tab=${t.id}`}
            className={`rounded-lg py-2 text-center text-sm font-semibold transition ${
              tab === t.id ? "bg-accent text-white dark:text-black" : "text-muted"
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

      <Link
        href={`/groups/${id}/expenses/new`}
        className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-full bg-accent px-6 py-3.5 text-base font-bold text-white shadow-lg transition-colors duration-200 hover:bg-accent-orange dark:text-black"
      >
        + Add expense
      </Link>
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
      <p className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted">
        Nothing here yet — add the first expense.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {items.map((item) =>
        item.kind === "expense" ? (
          <Link
            key={`e-${item.expense.id}`}
            href={`/groups/${group.id}/expenses/${item.expense.id}/edit`}
            className="flex items-center gap-3 rounded-2xl border border-border bg-card p-3.5 shadow-sm transition-colors duration-200 hover:border-accent"
          >
            <span className="text-2xl" title={categoryLabel(item.expense.category)}>
              {categoryIcon(item.expense.category)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-semibold">
                {item.expense.description}
              </span>
              <span className="block text-xs text-muted first-letter:uppercase">
                {name(item.expense.payerId)} paid · split{" "}
                {item.expense.splitType.toLowerCase()} between{" "}
                {item.expense.splits.length}
              </span>
            </span>
            <span className="text-right">
              <span className="block font-bold">
                {formatCents(item.expense.amountCents, item.expense.currency)}
              </span>
              <span className="block text-xs text-muted">
                {dateFmt.format(item.date)}
              </span>
            </span>
          </Link>
        ) : (
          <div
            key={`p-${item.payment.id}`}
            className="flex items-center gap-3 rounded-2xl border border-border bg-card p-3.5 opacity-90"
          >
            <span className="text-2xl">🤝</span>
            <span className="min-w-0 flex-1">
              <span className="block font-semibold first-letter:uppercase">
                {name(item.payment.fromId)} paid {name(item.payment.toId)}
              </span>
              <span className="block text-xs text-muted">
                {item.payment.note ?? "settlement"} · {dateFmt.format(item.date)}
              </span>
            </span>
            <span className="font-bold text-positive">
              {formatCents(item.payment.amountCents, item.payment.currency)}
            </span>
            <DeleteButton
              action={deletePayment.bind(null, item.payment.id)}
              label="✕"
              confirmText="Remove this settlement? Balances will update."
            />
          </div>
        )
      )}
    </div>
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
    <div className="space-y-6">
      <section>
        <h2 className="mb-2 text-sm font-bold text-muted">Net balances</h2>
        <div className="space-y-2">
          {rows.map(({ user, cents }) => (
            <div
              key={user.id}
              className="flex items-center justify-between rounded-2xl border border-border bg-card p-3.5"
            >
              <span className="font-semibold">
                {user.emoji} {user.name}
                {user.id === meId && <span className="text-muted"> (you)</span>}
              </span>
              {cents === 0 ? (
                <span className="text-sm text-muted">settled</span>
              ) : (
                <span
                  className={`font-bold ${cents > 0 ? "text-positive" : "text-negative"}`}
                >
                  {cents > 0 ? "gets back " : "owes "}
                  {formatCents(Math.abs(cents), group.currency)}
                </span>
              )}
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-bold text-muted">
          Suggested settlements ({transfers.length}{" "}
          {transfers.length === 1 ? "payment" : "payments"})
        </h2>
        {transfers.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-border p-5 text-center text-sm text-muted">
            All settled up 🎉
          </p>
        ) : (
          <div className="space-y-2">
            {transfers.map((t) => (
              <div
                key={`${t.fromId}-${t.toId}`}
                className="flex items-center justify-between gap-3 rounded-2xl border border-border bg-card p-3.5"
              >
                <span className="min-w-0 text-sm first-letter:uppercase">
                  <strong>{name(t.fromId)}</strong> pays{" "}
                  <strong>{name(t.toId)}</strong>{" "}
                  <span className="font-bold">
                    {formatCents(t.amountCents, group.currency)}
                  </span>
                </span>
                <Link
                  href={`/groups/${group.id}/settle?from=${t.fromId}&to=${t.toId}&amount=${(t.amountCents / 100).toFixed(2)}`}
                  className="shrink-0 rounded-full bg-accent px-3 py-2 text-xs font-bold text-white transition-colors duration-200 hover:bg-accent-orange dark:text-black"
                >
                  Settle
                </Link>
              </div>
            ))}
          </div>
        )}
        <div className="mt-2 text-right">
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
          <h2 className="mb-2 text-sm font-bold text-muted">
            Spending by category · {formatCents(totalSpent, group.currency)} total
          </h2>
          <div className="rounded-2xl border border-border bg-card p-4">
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
                  <div className="h-2 overflow-hidden rounded-full bg-background">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: `${Math.max(2, (cents / maxCategory) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
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
