import { prisma } from "@/lib/prisma";
import { loginAs, createUserAndLogin } from "../actions";
import SplashHero from "@/components/SplashHero";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const users = await prisma.user.findMany({ orderBy: { name: "asc" } });

  return (
    <div className="mx-auto max-w-sm">
      <SplashHero />

      <h1 className="mb-1 text-xl font-semibold">Who are you?</h1>
      <p className="mb-4 text-sm text-muted">
        Pick your name to start tracking expenses.
      </p>

      <ul className="mb-8">
        {users.map((user) => (
          <li key={user.id} className="border-b border-border">
            <form action={loginAs.bind(null, user.id)}>
              <button
                type="submit"
                className="flex w-full items-center gap-3 py-3.5 text-left font-medium transition-colors hover:text-accent"
              >
                <span className="text-xl">{user.emoji}</span>
                <span className="min-w-0 flex-1 truncate">{user.name}</span>
                <span aria-hidden className="text-muted">
                  ›
                </span>
              </button>
            </form>
          </li>
        ))}
        {users.length === 0 && (
          <li className="py-8 text-center text-sm text-muted">
            No one here yet — add yourself below.
          </li>
        )}
      </ul>

      <h2 className="mb-2 text-sm font-semibold text-muted">New here?</h2>
      <form action={createUserAndLogin} className="flex gap-2">
        <input
          name="emoji"
          placeholder="🙂"
          maxLength={4}
          className="w-14 rounded-sm border border-border bg-card p-3 text-center"
          aria-label="Emoji avatar"
        />
        <input
          name="name"
          required
          placeholder="Your name"
          className="min-w-0 flex-1 rounded-sm border border-border bg-card p-3"
        />
        <button
          type="submit"
          className="btn-flat bg-accent-vivid px-5 text-sm text-white"
        >
          Join
        </button>
      </form>
    </div>
  );
}
