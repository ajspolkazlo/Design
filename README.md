# 💸 SplitMate

A self-hosted, Splitwise-style expense splitter for a small group of friends.
Track shared expenses in groups, see who owes who, simplify debts, and settle up.
No accounts, no subscriptions, no external services — just a SQLite file.

## Features

- **Trust-based login** — a "who are you?" picker; anyone can add themselves by name
- **Groups** — e.g. "Sicily Trip", "Flat 4B", each with its own currency and members
- **Expenses** — description, amount, currency, date, payer, and a category with icons
- **Four split types** — equally, exact amounts, by percentage, or by shares/ratio
- **Edit & delete** expenses at any time; balances always recompute
- **Balances** — per-group net amounts, plus your overall position across all groups
- **Simplify debts** — a greedy algorithm suggests the minimum set of payments to settle (at most *n − 1* transfers)
- **Settle up** — one tap on a suggested settlement records a payment; custom payments too
- **Activity feed** — expenses and settlements, newest first
- **Multi-currency** — record an expense in another currency with a manual exchange rate to the group currency
- **CSV export** — download a group's full history
- **Spending by category** — a small chart on the balances tab
- Mobile-first responsive UI with light/dark mode

## Tech stack

Next.js (App Router) + TypeScript · Prisma + SQLite · Tailwind CSS

## Getting started

Requires Node.js 18.18+ (Node 20+ recommended).

```bash
npm install        # also generates the Prisma client (postinstall)
npm run db:setup   # creates prisma/dev.db, applies migrations, seeds demo data
npm run dev        # http://localhost:3000
```

That's it — open http://localhost:3000, pick a seeded user (Alice, Bob, Carol,
or Dave) and poke around the demo groups **Sicily Trip** and **Flat 4B**, or
add yourself from the login screen.

### Useful commands

| Command | What it does |
| --- | --- |
| `npm run dev` | Start the dev server |
| `npm run build && npm start` | Production build + serve |
| `npm run seed` | Re-run the seed script (idempotent) |
| `npx prisma studio` | Browse/edit the database in a GUI |
| `npm run lint` | ESLint |

### Resetting the data

The whole database is one file. Delete it and start over:

```bash
rm prisma/dev.db && npm run db:setup
```

## How balances work

- All money is stored as **integer cents** — no floating-point drift. Split
  remainders (e.g. €100 ÷ 3) are distributed one cent at a time, largest
  fractional share first, so splits always sum exactly to the total.
- The payer of an expense is credited the full amount; each participant is
  debited their share. A settlement payment credits the sender and debits the
  receiver.
- Foreign-currency expenses are converted to the group currency using the
  manual exchange rate entered on the expense.
- **Simplify debts** matches the largest debtor with the largest creditor
  repeatedly, which settles the whole group in at most *n − 1* payments.

## Project layout

```
app/                 # Next.js App Router pages + server actions (app/actions.ts)
  groups/[id]/       # group feed & balances, expense forms, settle up, CSV export
components/          # client components (expense form, delete button)
lib/                 # money math, split & simplify-debts algorithms, balances, session
prisma/              # schema, migrations, seed script (SQLite db lives here too)
```

## Non-goals

No payment processing, no email, no real auth — it's for a small group of
friends who trust each other. Don't expose it to the public internet without
putting something in front of it (VPN, Tailscale, basic auth on a reverse proxy).
