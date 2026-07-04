import { prisma } from "./prisma";
import { simplifyDebts, toGroupCents, type Transfer } from "./money";

export type GroupBalances = {
  /** userId -> net cents in group currency (positive = is owed) */
  net: Map<string, number>;
  transfers: Transfer[];
};

/**
 * Net balance per member of one group, in the group's currency.
 * Payer is credited the full expense; each split participant is debited
 * their share. A settlement payment credits the sender and debits the
 * receiver.
 */
export async function getGroupBalances(groupId: string): Promise<GroupBalances> {
  const [members, expenses, payments] = await Promise.all([
    prisma.groupMember.findMany({ where: { groupId } }),
    prisma.expense.findMany({ where: { groupId }, include: { splits: true } }),
    prisma.payment.findMany({ where: { groupId } }),
  ]);

  const net = new Map<string, number>();
  for (const m of members) net.set(m.userId, 0);
  const add = (userId: string, cents: number) =>
    net.set(userId, (net.get(userId) ?? 0) + cents);

  for (const e of expenses) {
    const totalGroupCents = toGroupCents(e.amountCents, e.exchangeRate);
    add(e.payerId, totalGroupCents);
    // Convert each split with the same rate; pin the last split so the
    // converted shares sum exactly to the converted total.
    let allocated = 0;
    e.splits.forEach((s, i) => {
      const share =
        i === e.splits.length - 1
          ? totalGroupCents - allocated
          : toGroupCents(s.amountCents, e.exchangeRate);
      allocated += share;
      add(s.userId, -share);
    });
  }

  for (const p of payments) {
    add(p.fromId, p.amountCents);
    add(p.toId, -p.amountCents);
  }

  return { net, transfers: simplifyDebts(new Map(net)) };
}

export type OverallEntry = {
  currency: string;
  /** positive = the current user is owed this much overall in this currency */
  netCents: number;
};

/**
 * Overall net position of one user across all their groups, bucketed by
 * group currency (no cross-currency conversion).
 */
export async function getOverallBalances(userId: string): Promise<{
  perGroup: { groupId: string; groupName: string; currency: string; netCents: number }[];
  totals: OverallEntry[];
}> {
  const memberships = await prisma.groupMember.findMany({
    where: { userId },
    include: { group: true },
  });

  const perGroup: { groupId: string; groupName: string; currency: string; netCents: number }[] = [];
  const totals = new Map<string, number>();

  for (const m of memberships) {
    const { net } = await getGroupBalances(m.groupId);
    const cents = net.get(userId) ?? 0;
    perGroup.push({
      groupId: m.groupId,
      groupName: m.group.name,
      currency: m.group.currency,
      netCents: cents,
    });
    totals.set(m.group.currency, (totals.get(m.group.currency) ?? 0) + cents);
  }

  return {
    perGroup,
    totals: [...totals.entries()].map(([currency, netCents]) => ({ currency, netCents })),
  };
}
