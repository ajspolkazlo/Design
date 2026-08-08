import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import ExpenseForm, { type ExpenseFormInitial } from "@/components/ExpenseForm";
import DeleteButton from "@/components/DeleteButton";
import { deleteExpense } from "@/app/actions";
import type { SplitType } from "@/lib/money";

export const dynamic = "force-dynamic";

export default async function EditExpensePage({
  params,
}: {
  params: Promise<{ id: string; expenseId: string }>;
}) {
  const { id, expenseId } = await params;
  const [group, expense] = await Promise.all([
    prisma.group.findUnique({
      where: { id },
      include: { members: { include: { user: true } } },
    }),
    prisma.expense.findUnique({
      where: { id: expenseId },
      include: { splits: true },
    }),
  ]);
  if (!group || !expense || expense.groupId !== id) notFound();

  const weights: Record<string, string> = {};
  for (const s of expense.splits) {
    if (expense.splitType === "EXACT") {
      weights[s.userId] = (s.amountCents / 100).toFixed(2);
    } else if (s.weight !== null) {
      weights[s.userId] = String(s.weight);
    }
  }

  const initial: ExpenseFormInitial = {
    description: expense.description,
    amount: (expense.amountCents / 100).toFixed(2),
    currency: expense.currency,
    exchangeRate: String(expense.exchangeRate),
    date: expense.date.toISOString().slice(0, 10),
    category: expense.category,
    payerId: expense.payerId,
    splitType: expense.splitType as SplitType,
    participantIds: expense.splits.map((s) => s.userId),
    weights,
  };

  return (
    <div className="mx-auto max-w-sm">
      <div className="flex items-start justify-between">
        <div>
          <Link href={`/groups/${id}`} className="text-sm text-muted">
            ← {group.name}
          </Link>
          <h1 className="mt-1 mb-4 text-2xl font-bold">Edit expense</h1>
        </div>
        <DeleteButton
          action={deleteExpense.bind(null, expenseId)}
          confirmText="Delete this expense? Balances will update."
        />
      </div>
      <ExpenseForm
        groupId={id}
        groupCurrency={group.currency}
        expenseId={expenseId}
        members={group.members.map((m) => ({
          id: m.user.id,
          name: m.user.name,
          emoji: m.user.emoji,
        }))}
        initial={initial}
      />
    </div>
  );
}
