import { prisma } from "@/lib/prisma";
import { loginAs, createUserAndLogin } from "../actions";
import BrandBlobs from "@/components/BrandBlobs";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const users = await prisma.user.findMany({ orderBy: { name: "asc" } });

  return (
    <div className="relative mx-auto max-w-sm pt-24">
      <BrandBlobs />
      <h1 className="mb-1 font-display text-2xl font-bold lowercase">
        who are you?
      </h1>
      <p className="mb-6 text-sm text-muted">
        Pick your name to start tracking expenses.
      </p>

      <div className="mb-8 grid grid-cols-2 gap-3">
        {users.map((user) => (
          <form key={user.id} action={loginAs.bind(null, user.id)}>
            <button
              type="submit"
              className="flex w-full items-center gap-3 rounded-2xl border border-border bg-card p-4 text-left font-medium shadow-sm transition-colors duration-200 hover:border-accent active:scale-[0.98]"
            >
              <span className="text-2xl">{user.emoji}</span>
              <span className="truncate">{user.name}</span>
            </button>
          </form>
        ))}
        {users.length === 0 && (
          <p className="col-span-2 rounded-xl border border-dashed border-border p-4 text-center text-sm text-muted">
            No one here yet — add yourself below.
          </p>
        )}
      </div>

      <h2 className="mb-2 text-sm font-semibold text-muted">New here?</h2>
      <form action={createUserAndLogin} className="flex gap-2">
        <input
          name="emoji"
          placeholder="🙂"
          maxLength={4}
          className="w-14 rounded-xl border border-border bg-card p-3 text-center"
          aria-label="Emoji avatar"
        />
        <input
          name="name"
          required
          placeholder="Your name"
          className="min-w-0 flex-1 rounded-xl border border-border bg-card p-3"
        />
        <button
          type="submit"
          className="pop rounded-full bg-accent px-5 py-3 font-semibold text-white transition-colors duration-200 hover:bg-accent-orange dark:text-black"
        >
          Join
        </button>
      </form>
    </div>
  );
}
