"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const links = [
  { href: "/teams", label: "Teams" },
  { href: "/matches", label: "Matches" },
  { href: "/predictions", label: "Predictions" },
  { href: "/simulate", label: "Groups" },
  { href: "/players", label: "Players" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-white/8 bg-neutral-950/80 backdrop-blur-md sticky top-0 z-50 h-14 flex items-center">
      <div className="container mx-auto px-4 flex items-center gap-1">
        <Link
          href="/"
          className="font-bold text-white mr-6 flex items-center gap-2 text-sm shrink-0"
        >
          <span className="text-lg">⚽</span>
          Raumdeuter
        </Link>
        <div className="flex items-center gap-0.5 overflow-x-auto">
          {links.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "px-3 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap",
                pathname.startsWith(href)
                  ? "bg-white/10 text-white font-medium"
                  : "text-white/50 hover:text-white hover:bg-white/5"
              )}
            >
              {label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
