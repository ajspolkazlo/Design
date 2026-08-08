import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { recordPayment } from "@/app/actions";

export const dynamic = "force-dynamic";

export default async function SettlePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ from?: string; to?: string; amount?: string }>;
}) {
  const { id } = await params;
  const { from, to, amount } = await searchParams;
  const group = await prisma.group.findUnique({
    where: { id },
    include: { members: { include: { user: true } } },
  });
  if (!group) notFound();

  const members = group.members.map((m) => m.user);
  const inputCls = "w-full rounded-xl border border-border bg-card p-3";

  return (
    <div className="mx-auto max-w-sm">
      <Link href={`/groups/${id}?tab=balances`} className="text-sm text-muted">
        ← {group.name}
      </Link>
      <h1 className="mt-1 mb-1 text-2xl font-bold">Settle up</h1>
      <p className="mb-4 text-sm text-muted">
        Record a payment made outside the app (cash, bank transfer, …).
      </p>

      <form action={recordPayment.bind(null, id)} className="space-y-5">
        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="fromId">
            Who paid
          </label>
          <select id="fromId" name="fromId" defaultValue={from} className={inputCls}>
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.emoji} {m.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="toId">
            Who received
          </label>
          <select
            id="toId"
            name="toId"
            defaultValue={to ?? members.find((m) => m.id !== from)?.id}
            className={inputCls}
          >
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.emoji} {m.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="amount">
            Amount ({group.currency})
          </label>
          <input
            id="amount"
            name="amount"
            required
            inputMode="decimal"
            placeholder="0.00"
            defaultValue={amount}
            className={inputCls}
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="note">
            Note (optional)
          </label>
          <input
            id="note"
            name="note"
            placeholder="e.g. Revolut transfer"
            className={inputCls}
          />
        </div>

        <button
          type="submit"
          className="w-full glossy rounded-full bg-accent p-3 font-semibold text-white transition-colors duration-200 hover:bg-accent-orange dark:text-black"
        >
          Record payment
        </button>
      </form>
    </div>
  );
}
