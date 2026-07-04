import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { addGroupMembers } from "../../../actions";

export const dynamic = "force-dynamic";

export default async function MembersPage({
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

  const memberIds = new Set(group.members.map((m) => m.userId));
  const nonMembers = (
    await prisma.user.findMany({ orderBy: { name: "asc" } })
  ).filter((u) => !memberIds.has(u.id));

  return (
    <div className="mx-auto max-w-sm">
      <Link href={`/groups/${id}`} className="text-sm text-muted">
        ← {group.name}
      </Link>
      <h1 className="mt-1 mb-4 text-2xl font-bold">Members</h1>

      <ul className="mb-6 space-y-2">
        {group.members.map((m) => (
          <li
            key={m.id}
            className="rounded-xl border border-border bg-card p-3 font-medium"
          >
            {m.user.emoji} {m.user.name}
          </li>
        ))}
      </ul>

      {nonMembers.length > 0 ? (
        <form action={addGroupMembers.bind(null, id)}>
          <h2 className="mb-2 text-sm font-semibold text-muted">Add people</h2>
          <div className="mb-4 space-y-2">
            {nonMembers.map((user) => (
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
          </div>
          <button
            type="submit"
            className="w-full rounded-xl bg-accent p-3 font-semibold text-white dark:text-black"
          >
            Add to group
          </button>
        </form>
      ) : (
        <p className="text-sm text-muted">
          Everyone is already in this group. New friends can add themselves
          from the login screen.
        </p>
      )}
    </div>
  );
}
