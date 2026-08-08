import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Outfit, Silkscreen } from "next/font/google";
import "./globals.css";
import { getCurrentUser } from "@/lib/session";
import { logout } from "./actions";
import BottomNav from "@/components/BottomNav";

const outfit = Outfit({ subsets: ["latin"], variable: "--font-body" });
const silkscreen = Silkscreen({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-display-face",
});

export const metadata: Metadata = {
  title: "Bittersplit",
  description: "Track shared expenses with friends and see who owes who",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#ff4c91",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const user = await getCurrentUser();
  return (
    <html
      lang="en"
      className={`h-full antialiased ${outfit.variable} ${silkscreen.variable}`}
    >
      <body className="min-h-full flex flex-col">
        {/* Solid hot-pink app bar. Text here is kept large/bold — white on
            this pink clears AA for large text but not for small copy. */}
        <header className="sticky top-0 z-20 bg-accent-vivid">
          <div className="mx-auto flex h-14 w-full max-w-2xl items-center justify-between px-4">
            <Link
              href="/"
              className="font-display text-base lowercase tracking-tight text-white"
            >
              bittersplit
            </Link>
            {user && (
              <form action={logout} className="flex items-center gap-2">
                <span className="text-sm font-semibold text-white">
                  {user.emoji} {user.name}
                </span>
                <button
                  type="submit"
                  className="btn-flat border border-white/70 px-2.5 py-1 text-[11px] text-white"
                >
                  Switch
                </button>
              </form>
            )}
          </div>
        </header>
        <main className="relative mx-auto w-full max-w-2xl flex-1 px-4 py-5 pb-28">
          {children}
        </main>
        <BottomNav />
      </body>
    </html>
  );
}
