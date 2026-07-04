import { cookies } from "next/headers";
import { prisma } from "./prisma";

const COOKIE_NAME = "splitmate_user";

export async function getCurrentUser() {
  const store = await cookies();
  const userId = store.get(COOKIE_NAME)?.value;
  if (!userId) return null;
  return prisma.user.findUnique({ where: { id: userId } });
}

export async function setCurrentUser(userId: string) {
  const store = await cookies();
  store.set(COOKIE_NAME, userId, {
    httpOnly: true,
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 365,
    path: "/",
  });
}

export async function clearCurrentUser() {
  const store = await cookies();
  store.delete(COOKIE_NAME);
}
