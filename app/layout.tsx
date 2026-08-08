import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Inter, Space_Mono } from "next/font/google";
import "./globals.css";
import { getCurrentUser } from "@/lib/session";
import { logout } from "./actions";

const inter = Inter({ subsets: ["latin"], variable: "--font-body" });
const spaceMono = Space_Mono({
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
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const user = await getCurrentUser();
  return (
    <html
      lang="en"
      className={`h-full antialiased ${inter.variable} ${spaceMono.variable}`}
    >
      <body className="min-h-full flex flex-col">
        <header className="sticky top-0 z-10 border-b border-border bg-card/95 backdrop-blur">
          <div className="mx-auto flex h-14 w-full max-w-2xl items-center justify-between px-4">
            <Link href="/" className="flex items-center gap-2">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-2xl bg-accent-vivid font-display text-xs font-bold text-white">
                bs
              </span>
              <span className="font-display text-lg font-bold tracking-tight text-foreground lowercase">
                bittersplit
              </span>
            </Link>
            {user && (
              <form action={logout} className="flex items-center gap-3">
                <span className="text-sm text-muted">
                  {user.emoji} {user.name}
                </span>
                <button
                  type="submit"
                  className="rounded-lg border border-border px-2.5 py-1 text-xs text-muted hover:text-foreground"
                >
                  Switch
                </button>
              </form>
            )}
          </div>
        </header>
        <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-5 pb-24">
          {children}
        </main>
      </body>
    </html>
  );
}
