"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Black bottom tab bar, matching the real app's persistent navigation:
 * thin outline icons over a near-black bar, white label for the active
 * tab and grey for the rest. Links only to routes that already exist.
 */
const TABS = [
  { href: "/", label: "Groups", icon: GroupsIcon },
  { href: "/groups/new", label: "New", icon: PlusIcon },
  { href: "/login", label: "Switch", icon: PersonIcon },
];

export default function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 bg-tabbar pb-[env(safe-area-inset-bottom)]">
      <ul className="mx-auto flex w-full max-w-2xl">
        {TABS.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <li key={href} className="flex-1">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex flex-col items-center gap-1 py-2.5 text-[11px] transition-colors ${
                  active ? "text-white" : "text-white/45 hover:text-white/70"
                }`}
              >
                <Icon />
                <span className={active ? "font-semibold" : undefined}>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

const strokeProps = {
  width: 22,
  height: 22,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

function GroupsIcon() {
  return (
    <svg {...strokeProps}>
      <path d="M3 6.5h18M3 12h18M3 17.5h18" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg {...strokeProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8.5v7M8.5 12h7" />
    </svg>
  );
}

function PersonIcon() {
  return (
    <svg {...strokeProps}>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 19.5a7 7 0 0 1 14 0" />
    </svg>
  );
}
