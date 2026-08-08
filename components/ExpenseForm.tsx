"use client";

import { useActionState, useMemo, useState } from "react";
import { CATEGORIES } from "@/lib/categories";
import { CURRENCIES, formatCents, parseAmountToCents, type SplitType } from "@/lib/money";
import { saveExpense, type ExpenseActionState } from "@/app/actions";

type Member = { id: string; name: string; emoji: string };

export type ExpenseFormInitial = {
  description: string;
  amount: string;
  currency: string;
  exchangeRate: string;
  date: string; // yyyy-mm-dd
  category: string;
  payerId: string;
  splitType: SplitType;
  participantIds: string[];
  weights: Record<string, string>;
};

const SPLIT_TABS: { id: SplitType; label: string }[] = [
  { id: "EQUAL", label: "Equally" },
  { id: "EXACT", label: "Amounts" },
  { id: "PERCENT", label: "Percent" },
  { id: "SHARES", label: "Shares" },
];

export default function ExpenseForm({
  groupId,
  groupCurrency,
  members,
  expenseId,
  initial,
}: {
  groupId: string;
  groupCurrency: string;
  members: Member[];
  expenseId?: string;
  initial?: ExpenseFormInitial;
}) {
  const [state, formAction, pending] = useActionState<ExpenseActionState, FormData>(
    saveExpense.bind(null, groupId, expenseId ?? null),
    { error: null }
  );

  const [splitType, setSplitType] = useState<SplitType>(initial?.splitType ?? "EQUAL");
  const [currency, setCurrency] = useState(initial?.currency ?? groupCurrency);
  const [amount, setAmount] = useState(initial?.amount ?? "");
  const [participantIds, setParticipantIds] = useState<string[]>(
    initial?.participantIds ?? members.map((m) => m.id)
  );
  const [weights, setWeights] = useState<Record<string, string>>(initial?.weights ?? {});

  const toggleParticipant = (id: string) =>
    setParticipantIds((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    );

  const amountCents = parseAmountToCents(amount);

  // Live feedback: what's still unassigned for EXACT / PERCENT splits.
  const splitHint = useMemo(() => {
    const selected = members.filter((m) => participantIds.includes(m.id));
    if (selected.length === 0) return "Select at least one person";
    if (splitType === "EXACT" && amountCents !== null) {
      const assigned = selected.reduce(
        (acc, m) => acc + (parseAmountToCents(weights[m.id] || "0") ?? 0),
        0
      );
      const left = amountCents - assigned;
      if (left === 0) return "✓ adds up";
      return `${formatCents(Math.abs(left), currency)} ${left > 0 ? "left to assign" : "too much"}`;
    }
    if (splitType === "PERCENT") {
      const assigned = selected.reduce(
        (acc, m) => acc + (parseFloat(weights[m.id] || "0") || 0),
        0
      );
      const left = 100 - assigned;
      if (Math.abs(left) < 0.01) return "✓ adds up to 100%";
      return `${Math.abs(left).toFixed(1)}% ${left > 0 ? "left" : "over"}`;
    }
    if (splitType === "EQUAL" && amountCents !== null) {
      return `${formatCents(Math.round(amountCents / selected.length), currency)} each`;
    }
    return null;
  }, [members, participantIds, splitType, amountCents, weights, currency]);

  const inputCls = "w-full rounded-sm border border-border bg-card p-3";

  return (
    <form action={formAction} className="space-y-5">
      <div>
        <label className="mb-1 block text-sm font-semibold" htmlFor="description">
          Description
        </label>
        <input
          id="description"
          name="description"
          required
          defaultValue={initial?.description}
          placeholder="e.g. Dinner at the trattoria"
          className={inputCls}
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="amount">
            Amount
          </label>
          <input
            id="amount"
            name="amount"
            required
            inputMode="decimal"
            placeholder="0.00"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className={inputCls}
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="currency">
            Currency
          </label>
          <select
            id="currency"
            name="currency"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className={inputCls}
          >
            {CURRENCIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      </div>

      {currency !== groupCurrency && (
        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="exchangeRate">
            Exchange rate (1 {currency} = ? {groupCurrency})
          </label>
          <input
            id="exchangeRate"
            name="exchangeRate"
            required
            inputMode="decimal"
            step="any"
            defaultValue={initial?.exchangeRate ?? ""}
            placeholder="e.g. 1.08"
            className={inputCls}
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="date">
            Date
          </label>
          <input
            id="date"
            name="date"
            type="date"
            required
            defaultValue={initial?.date ?? new Date().toISOString().slice(0, 10)}
            className={inputCls}
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="category">
            Category
          </label>
          <select
            id="category"
            name="category"
            defaultValue={initial?.category ?? "general"}
            className={inputCls}
          >
            {CATEGORIES.map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} {c.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-semibold" htmlFor="payerId">
          Paid by
        </label>
        <select
          id="payerId"
          name="payerId"
          defaultValue={initial?.payerId ?? members[0]?.id}
          className={inputCls}
        >
          {members.map((m) => (
            <option key={m.id} value={m.id}>
              {m.emoji} {m.name}
            </option>
          ))}
        </select>
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Split</legend>
        <input type="hidden" name="splitType" value={splitType} />
        <div className="mb-3 flex gap-5 border-b border-border">
          {SPLIT_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setSplitType(tab.id)}
              className={`-mb-px border-b-2 pb-2 text-xs font-semibold transition-colors ${
                splitType === tab.id
                  ? "border-accent-vivid text-foreground"
                  : "border-transparent text-muted hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="space-y-2">
          {members.map((m) => {
            const checked = participantIds.includes(m.id);
            return (
              <div
                key={m.id}
                className={`flex items-center gap-3 rounded-sm border p-3 ${
                  checked ? "border-border bg-card" : "border-transparent opacity-50"
                }`}
              >
                <input
                  type="checkbox"
                  name="participantIds"
                  value={m.id}
                  checked={checked}
                  onChange={() => toggleParticipant(m.id)}
                  className="size-5 accent-(--accent)"
                  aria-label={`Include ${m.name}`}
                />
                <span className="min-w-0 flex-1 truncate">
                  {m.emoji} {m.name}
                </span>
                {splitType !== "EQUAL" && checked && (
                  <div className="flex items-center gap-1">
                    <input
                      name={`weight_${m.id}`}
                      inputMode="decimal"
                      placeholder={splitType === "EXACT" ? "0.00" : splitType === "PERCENT" ? "%" : "1"}
                      value={weights[m.id] ?? ""}
                      onChange={(e) =>
                        setWeights((prev) => ({ ...prev, [m.id]: e.target.value }))
                      }
                      className="w-24 rounded-lg border border-border bg-background p-2 text-right text-sm"
                      aria-label={`Split value for ${m.name}`}
                    />
                    <span className="w-4 text-xs text-muted">
                      {splitType === "PERCENT" ? "%" : splitType === "SHARES" ? "×" : ""}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
        {splitHint && <p className="mt-2 text-sm text-muted">{splitHint}</p>}
      </fieldset>

      {state.error && (
        <p className="rounded-sm border border-negative/40 bg-negative/10 p-3 text-sm text-negative">
          {state.error}
        </p>
      )}

      <button
        type="submit"
        disabled={pending}
        className="w-full btn-flat bg-accent-vivid p-3.5 text-sm text-white disabled:opacity-60"
      >
        {pending ? "Saving…" : expenseId ? "Save changes" : "Add expense"}
      </button>
    </form>
  );
}
