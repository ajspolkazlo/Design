export type SplitType = "EQUAL" | "EXACT" | "PERCENT" | "SHARES";

export const CURRENCIES = ["EUR", "USD", "GBP", "CHF", "SEK", "PLN", "JPY"] as const;

export function formatCents(cents: number, currency: string): string {
  const amount = cents / 100;
  try {
    return new Intl.NumberFormat("en", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

export function parseAmountToCents(input: string): number | null {
  const normalized = input.trim().replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null;
  return Math.round(parseFloat(normalized) * 100);
}

/**
 * Compute per-person owed amounts in cents. The results always sum exactly to
 * totalCents; rounding leftovers are distributed one cent at a time starting
 * from the first participant.
 *
 * weights: EQUAL ignores them, EXACT expects cents per person, PERCENT expects
 * percentages, SHARES expects share counts.
 */
export function computeSplits(
  totalCents: number,
  participants: { userId: string; weight: number }[],
  splitType: SplitType
): { userId: string; amountCents: number; weight: number | null }[] {
  if (participants.length === 0) throw new Error("At least one participant is required");
  if (totalCents <= 0) throw new Error("Amount must be positive");

  if (splitType === "EXACT") {
    const sum = participants.reduce((acc, p) => acc + Math.round(p.weight), 0);
    if (sum !== totalCents) {
      throw new Error("Exact amounts must add up to the total");
    }
    return participants.map((p) => ({
      userId: p.userId,
      amountCents: Math.round(p.weight),
      weight: null,
    }));
  }

  let weights: number[];
  if (splitType === "EQUAL") {
    weights = participants.map(() => 1);
  } else if (splitType === "PERCENT") {
    weights = participants.map((p) => p.weight);
    const totalPct = weights.reduce((a, b) => a + b, 0);
    if (Math.abs(totalPct - 100) > 0.01) {
      throw new Error("Percentages must add up to 100");
    }
    if (weights.some((w) => w < 0)) throw new Error("Percentages cannot be negative");
  } else {
    weights = participants.map((p) => p.weight);
    if (weights.some((w) => w <= 0 || !Number.isFinite(w))) {
      throw new Error("Shares must be positive numbers");
    }
  }

  const totalWeight = weights.reduce((a, b) => a + b, 0);
  const raw = weights.map((w) => (totalCents * w) / totalWeight);
  const floored = raw.map(Math.floor);
  let remainder = totalCents - floored.reduce((a, b) => a + b, 0);

  // Hand out leftover cents to those with the largest fractional part first.
  const order = raw
    .map((r, i) => ({ i, frac: r - Math.floor(r) }))
    .sort((a, b) => b.frac - a.frac)
    .map((x) => x.i);
  const result = [...floored];
  for (const i of order) {
    if (remainder <= 0) break;
    result[i] += 1;
    remainder -= 1;
  }

  return participants.map((p, i) => ({
    userId: p.userId,
    amountCents: result[i],
    weight: splitType === "EQUAL" ? null : weights[i],
  }));
}

export type Transfer = { fromId: string; toId: string; amountCents: number };

/**
 * Greedy debt simplification: repeatedly match the largest debtor with the
 * largest creditor. Produces at most (n - 1) transfers for n people.
 * balances: userId -> net cents (positive = is owed money).
 */
export function simplifyDebts(balances: Map<string, number>): Transfer[] {
  const creditors: { id: string; amount: number }[] = [];
  const debtors: { id: string; amount: number }[] = [];
  for (const [id, cents] of balances) {
    if (cents > 0) creditors.push({ id, amount: cents });
    else if (cents < 0) debtors.push({ id, amount: -cents });
  }
  creditors.sort((a, b) => b.amount - a.amount);
  debtors.sort((a, b) => b.amount - a.amount);

  const transfers: Transfer[] = [];
  let ci = 0;
  let di = 0;
  while (ci < creditors.length && di < debtors.length) {
    const pay = Math.min(creditors[ci].amount, debtors[di].amount);
    transfers.push({ fromId: debtors[di].id, toId: creditors[ci].id, amountCents: pay });
    creditors[ci].amount -= pay;
    debtors[di].amount -= pay;
    if (creditors[ci].amount === 0) ci++;
    if (debtors[di].amount === 0) di++;
  }
  return transfers;
}

/**
 * Convert an expense amount into group-currency cents using its manual
 * exchange rate (rate = group-currency units per expense-currency unit).
 */
export function toGroupCents(amountCents: number, exchangeRate: number): number {
  return Math.round(amountCents * exchangeRate);
}
