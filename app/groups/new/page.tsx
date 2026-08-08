import { redirect } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { getCurrentUser } from "@/lib/session";
import { CURRENCIES } from "@/lib/money";
import { createGroup } from "../../actions";

export const dynamic = "force-dynamic";

export default async function NewGroupPage() {
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  const others = await prisma.user.findMany({
    where: { id: { not: me.id } },
    orderBy: { name: "asc" },
  });

  return (
    <div className="mx-auto max-w-sm">
      <h1 className="mb-4 font-display text-2xl font-bold">New group</h1>
      <form action={createGroup} className="space-y-5">
        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="name">
            Group name
          </label>
          <input
            id="name"
            name="name"
            required
            placeholder="e.g. Sicily Trip"
            className="w-full rounded-xl border border-border bg-card p-3"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="currency">
            Currency
          </label>
          <select
            id="currency"
            name="currency"
            defaultValue="EUR"
            className="w-full rounded-xl border border-border bg-card p-3"
          >
            {CURRENCIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        <fieldset>
          <legend className="mb-2 text-sm font-semibold">
            Members (you&apos;re included automatically)
          </legend>
          <div className="space-y-2">
            {others.map((user) => (
              <label
                key={user.id}
                className="flex items-center gap-3 rounded-xl border border-border bg-card p-3"
              >
                <input
                  type="checkbox"
                  name="memberIds"
                  value={user.id}
                  className="size-5 accent-(--accent)"
                />
                <span>
                  {user.emoji} {user.name}
                </span>
              </label>
            ))}
            {others.length === 0 && (
              <p className="text-sm text-muted">
                No other users yet — friends can add themselves from the login
                screen, then you can add them to the group.
              </p>
            )}
          </div>
        </fieldset>

        <button
          type="submit"
          className="w-full pop rounded-full bg-accent p-3 font-semibold text-white transition-colors duration-200 hover:bg-accent-orange dark:text-black"
        >
          Create group
        </button>
      </form>
    </div>
  );
}
