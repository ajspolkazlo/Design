import { PrismaClient } from "@prisma/client";
import { computeSplits } from "../lib/money";

const prisma = new PrismaClient();

async function main() {
  const [alice, bob, carol, dave] = await Promise.all(
    [
      { name: "Alice", emoji: "🦊" },
      { name: "Bob", emoji: "🐻" },
      { name: "Carol", emoji: "🐙" },
      { name: "Dave", emoji: "🦉" },
    ].map((data) =>
      prisma.user.upsert({ where: { name: data.name }, update: {}, create: data })
    )
  );

  const existing = await prisma.group.findFirst({ where: { name: "Sicily Trip" } });
  if (existing) {
    console.log("Seed data already present, skipping.");
    return;
  }

  const sicily = await prisma.group.create({
    data: {
      name: "Sicily Trip",
      currency: "EUR",
      members: {
        create: [alice, bob, carol, dave].map((u) => ({ userId: u.id })),
      },
    },
  });

  const flat = await prisma.group.create({
    data: {
      name: "Flat 4B",
      currency: "EUR",
      members: { create: [alice, bob, carol].map((u) => ({ userId: u.id })) },
    },
  });

  const daysAgo = (n: number) => new Date(Date.now() - n * 24 * 60 * 60 * 1000);

  async function addExpense(opts: {
    groupId: string;
    payerId: string;
    description: string;
    amountCents: number;
    category: string;
    date: Date;
    participants: { userId: string; weight: number }[];
    splitType?: "EQUAL" | "EXACT" | "PERCENT" | "SHARES";
  }) {
    const splitType = opts.splitType ?? "EQUAL";
    const splits = computeSplits(opts.amountCents, opts.participants, splitType);
    await prisma.expense.create({
      data: {
        groupId: opts.groupId,
        payerId: opts.payerId,
        description: opts.description,
        amountCents: opts.amountCents,
        currency: "EUR",
        date: opts.date,
        category: opts.category,
        splitType,
        splits: { create: splits },
      },
    });
  }

  await addExpense({
    groupId: sicily.id,
    payerId: alice.id,
    description: "Airbnb in Palermo",
    amountCents: 48000,
    category: "travel",
    date: daysAgo(10),
    participants: [alice, bob, carol, dave].map((u) => ({ userId: u.id, weight: 1 })),
  });

  await addExpense({
    groupId: sicily.id,
    payerId: bob.id,
    description: "Dinner at the trattoria",
    amountCents: 9650,
    category: "food",
    date: daysAgo(9),
    participants: [alice, bob, carol, dave].map((u) => ({ userId: u.id, weight: 1 })),
  });

  await addExpense({
    groupId: sicily.id,
    payerId: carol.id,
    description: "Rental car (Dave skipped it)",
    amountCents: 21000,
    category: "transport",
    date: daysAgo(8),
    splitType: "SHARES",
    participants: [
      { userId: alice.id, weight: 1 },
      { userId: bob.id, weight: 1 },
      { userId: carol.id, weight: 2 },
    ],
  });

  await addExpense({
    groupId: flat.id,
    payerId: alice.id,
    description: "July rent",
    amountCents: 180000,
    category: "rent",
    date: daysAgo(3),
    splitType: "PERCENT",
    participants: [
      { userId: alice.id, weight: 40 },
      { userId: bob.id, weight: 35 },
      { userId: carol.id, weight: 25 },
    ],
  });

  await addExpense({
    groupId: flat.id,
    payerId: bob.id,
    description: "Internet bill",
    amountCents: 4500,
    category: "utilities",
    date: daysAgo(2),
    participants: [alice, bob, carol].map((u) => ({ userId: u.id, weight: 1 })),
  });

  await prisma.payment.create({
    data: {
      groupId: sicily.id,
      fromId: dave.id,
      toId: alice.id,
      amountCents: 10000,
      currency: "EUR",
      date: daysAgo(1),
      note: "First chunk of the Airbnb",
    },
  });

  console.log("Seeded users Alice/Bob/Carol/Dave and groups 'Sicily Trip' & 'Flat 4B'.");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
