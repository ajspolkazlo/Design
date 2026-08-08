import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import ExpenseForm from "@/components/ExpenseForm";

export const dynamic = "force-dynamic";

export default async function NewExpensePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const group = await prisma.group.findUnique({
    where: { id },
    include: { members: { include: { user: true } } },
  });
  if (!group) notFound();

  return (
    <div className="mx-auto max-w-sm">
      <Link href={`/groups/${id}`} className="text-sm text-muted">
        ← {group.name}
      </Link>
      <h1 className="mt-1 mb-4 text-2xl font-bold">Add expense</h1>
      <ExpenseForm
        groupId={id}
        groupCurrency={group.currency}
        members={group.members.map((m) => ({
          id: m.user.id,
          name: m.user.name,
          emoji: m.user.emoji,
        }))}
      />
    </div>
  );
}
