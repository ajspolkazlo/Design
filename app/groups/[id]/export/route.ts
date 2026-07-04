import { prisma } from "@/lib/prisma";
import { categoryLabel } from "@/lib/categories";

function csvEscape(value: string): string {
  if (/[",\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const group = await prisma.group.findUnique({
    where: { id },
    include: {
      expenses: {
        include: { payer: true, splits: { include: { user: true } } },
        orderBy: { date: "asc" },
      },
      payments: { include: { from: true, to: true }, orderBy: { date: "asc" } },
    },
  });
  if (!group) return new Response("Not found", { status: 404 });

  const header = ["date", "type", "description", "category", "amount", "currency", "paid_by", "paid_to", "split"];
  const rows: string[][] = [];

  for (const e of group.expenses) {
    rows.push([
      e.date.toISOString().slice(0, 10),
      "expense",
      e.description,
      categoryLabel(e.category),
      (e.amountCents / 100).toFixed(2),
      e.currency,
      e.payer.name,
      "",
      e.splits
        .map((s) => `${s.user.name}: ${(s.amountCents / 100).toFixed(2)}`)
        .join("; "),
    ]);
  }
  for (const p of group.payments) {
    rows.push([
      p.date.toISOString().slice(0, 10),
      "settlement",
      p.note ?? "settle up",
      "",
      (p.amountCents / 100).toFixed(2),
      p.currency,
      p.from.name,
      p.to.name,
      "",
    ]);
  }

  rows.sort((a, b) => a[0].localeCompare(b[0]));

  const csv = [header, ...rows].map((r) => r.map(csvEscape).join(",")).join("\n");
  const filename = `${group.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-history.csv`;
  return new Response(csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${filename}"`,
    },
  });
}
