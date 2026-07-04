"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { setCurrentUser, clearCurrentUser, getCurrentUser } from "@/lib/session";
import { computeSplits, parseAmountToCents, type SplitType } from "@/lib/money";

// ---------- Users / session ----------

export async function loginAs(userId: string) {
  const user = await prisma.user.findUnique({ where: { id: userId } });
  if (!user) throw new Error("User not found");
  await setCurrentUser(user.id);
  redirect("/");
}

export async function createUserAndLogin(formData: FormData) {
  const name = String(formData.get("name") ?? "").trim();
  const emoji = String(formData.get("emoji") ?? "").trim() || "🙂";
  if (!name) throw new Error("Name is required");
  const existing = await prisma.user.findUnique({ where: { name } });
  const user = existing ?? (await prisma.user.create({ data: { name, emoji } }));
  await setCurrentUser(user.id);
  redirect("/");
}

export async function logout() {
  await clearCurrentUser();
  redirect("/login");
}

// ---------- Groups ----------

export async function createGroup(formData: FormData) {
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  const name = String(formData.get("name") ?? "").trim();
  const currency = String(formData.get("currency") ?? "EUR");
  const memberIds = formData.getAll("memberIds").map(String);
  if (!name) throw new Error("Group name is required");

  const uniqueMemberIds = [...new Set([me.id, ...memberIds])];
  const group = await prisma.group.create({
    data: {
      name,
      currency,
      members: { create: uniqueMemberIds.map((userId) => ({ userId })) },
    },
  });
  revalidatePath("/");
  redirect(`/groups/${group.id}`);
}

export async function addGroupMembers(groupId: string, formData: FormData) {
  const memberIds = formData.getAll("memberIds").map(String);
  const existing = await prisma.groupMember.findMany({ where: { groupId } });
  const existingIds = new Set(existing.map((m) => m.userId));
  const toAdd = memberIds.filter((id) => !existingIds.has(id));
  if (toAdd.length > 0) {
    await prisma.groupMember.createMany({
      data: toAdd.map((userId) => ({ groupId, userId })),
    });
  }
  revalidatePath(`/groups/${groupId}`);
  redirect(`/groups/${groupId}/members`);
}

// ---------- Expenses ----------

type ParsedExpenseForm = {
  description: string;
  amountCents: number;
  currency: string;
  exchangeRate: number;
  date: Date;
  category: string;
  payerId: string;
  splitType: SplitType;
  splits: { userId: string; amountCents: number; weight: number | null }[];
};

function parseExpenseForm(formData: FormData, groupCurrency: string): ParsedExpenseForm {
  const description = String(formData.get("description") ?? "").trim();
  if (!description) throw new Error("Description is required");

  const amountCents = parseAmountToCents(String(formData.get("amount") ?? ""));
  if (amountCents === null || amountCents <= 0) throw new Error("Enter a valid amount");

  const currency = String(formData.get("currency") ?? groupCurrency);
  let exchangeRate = 1;
  if (currency !== groupCurrency) {
    exchangeRate = parseFloat(String(formData.get("exchangeRate") ?? "1"));
    if (!Number.isFinite(exchangeRate) || exchangeRate <= 0) {
      throw new Error("Enter a valid exchange rate");
    }
  }

  const dateStr = String(formData.get("date") ?? "");
  const date = dateStr ? new Date(dateStr + "T12:00:00") : new Date();
  if (isNaN(date.getTime())) throw new Error("Invalid date");

  const category = String(formData.get("category") ?? "general");
  const payerId = String(formData.get("payerId") ?? "");
  if (!payerId) throw new Error("Select who paid");

  const splitType = String(formData.get("splitType") ?? "EQUAL") as SplitType;
  const participantIds = formData.getAll("participantIds").map(String);
  if (participantIds.length === 0) throw new Error("Select at least one person to split with");

  const participants = participantIds.map((userId) => {
    if (splitType === "EQUAL") return { userId, weight: 1 };
    const raw = String(formData.get(`weight_${userId}`) ?? "").trim();
    if (splitType === "EXACT") {
      const cents = parseAmountToCents(raw || "0");
      if (cents === null) throw new Error("Enter valid exact amounts");
      return { userId, weight: cents };
    }
    const num = parseFloat(raw || "0");
    if (!Number.isFinite(num)) throw new Error("Enter valid split values");
    return { userId, weight: num };
  });

  const splits = computeSplits(amountCents, participants, splitType);
  return { description, amountCents, currency, exchangeRate, date, category, payerId, splitType, splits };
}

export type ExpenseActionState = { error: string | null };

export async function saveExpense(
  groupId: string,
  expenseId: string | null,
  _prev: ExpenseActionState,
  formData: FormData
): Promise<ExpenseActionState> {
  try {
    const group = await prisma.group.findUniqueOrThrow({ where: { id: groupId } });
    const parsed = parseExpenseForm(formData, group.currency);
    const data = {
      payerId: parsed.payerId,
      description: parsed.description,
      amountCents: parsed.amountCents,
      currency: parsed.currency,
      exchangeRate: parsed.exchangeRate,
      date: parsed.date,
      category: parsed.category,
      splitType: parsed.splitType,
      splits: { create: parsed.splits },
    };
    if (expenseId) {
      await prisma.$transaction([
        prisma.expenseSplit.deleteMany({ where: { expenseId } }),
        prisma.expense.update({ where: { id: expenseId }, data }),
      ]);
    } else {
      await prisma.expense.create({ data: { groupId, ...data } });
    }
  } catch (e) {
    return { error: e instanceof Error ? e.message : "Something went wrong" };
  }
  revalidatePath(`/groups/${groupId}`);
  redirect(`/groups/${groupId}`);
}

export async function deleteExpense(expenseId: string) {
  const expense = await prisma.expense.delete({ where: { id: expenseId } });
  revalidatePath(`/groups/${expense.groupId}`);
  redirect(`/groups/${expense.groupId}`);
}

// ---------- Settle up ----------

export async function recordPayment(groupId: string, formData: FormData) {
  const fromId = String(formData.get("fromId") ?? "");
  const toId = String(formData.get("toId") ?? "");
  const amountCents = parseAmountToCents(String(formData.get("amount") ?? ""));
  const note = String(formData.get("note") ?? "").trim() || null;
  if (!fromId || !toId || fromId === toId) throw new Error("Pick two different people");
  if (amountCents === null || amountCents <= 0) throw new Error("Enter a valid amount");

  const group = await prisma.group.findUniqueOrThrow({ where: { id: groupId } });
  await prisma.payment.create({
    data: { groupId, fromId, toId, amountCents, currency: group.currency, note },
  });
  revalidatePath(`/groups/${groupId}`);
  redirect(`/groups/${groupId}?tab=balances`);
}

export async function deletePayment(paymentId: string) {
  const payment = await prisma.payment.delete({ where: { id: paymentId } });
  revalidatePath(`/groups/${payment.groupId}`);
  redirect(`/groups/${payment.groupId}`);
}
