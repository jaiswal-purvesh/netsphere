"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearToken, getToken } from "@/lib/api";
import { IconBell, IconChevronDown, IconLogout, IconSearch, NAV_ICONS } from "@/lib/icons";

type NavItem = { label: string; href: string; implemented: boolean };
type NavGroup = { label: string; items: NavItem[] };

// The full left-nav from the product spec, grouped by function the way a
// modern enterprise network console organizes its estate (overview →
// network → security → automation → operations → system). Only a subset
// is implemented in this delivery; everything else routes to the generic
// [module] "not implemented yet" page rather than a fake screen — see
// docs/ROADMAP.md for what phase adds each.
const NAV_GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [{ label: "Dashboard", href: "/dashboard", implemented: true }],
  },
  {
    label: "Network",
    items: [
      { label: "Network Inventory", href: "/network-inventory", implemented: true },
      { label: "IPAM", href: "/ipam", implemented: true },
      { label: "IPAM Sync", href: "/ipam-sync", implemented: true },
      { label: "Subnet Calculator", href: "/subnet-calculator", implemented: true },
      { label: "Topology", href: "/topology", implemented: true },
      { label: "Path Analyzer", href: "/path-analyzer", implemented: true },
      { label: "Routing", href: "/routing", implemented: true },
      { label: "Cloud Networks", href: "/cloud-networks", implemented: true },
      { label: "Connectivity", href: "/connectivity", implemented: true },
      { label: "Naming", href: "/naming", implemented: true },
    ],
  },
  {
    label: "Security",
    items: [
      { label: "Firewalls", href: "/firewalls", implemented: true },
      { label: "Security Policies", href: "/security-policies", implemented: true },
      { label: "Firewall Automation", href: "/fw-automation", implemented: true },
    ],
  },
  {
    label: "Automation",
    items: [
      { label: "Automation", href: "/automation", implemented: true },
      { label: "Integrations", href: "/integrations", implemented: true },
    ],
  },
  {
    label: "Operations",
    items: [
      { label: "Changes", href: "/changes", implemented: false },
      { label: "Compliance", href: "/compliance", implemented: false },
      { label: "Monitoring", href: "/monitoring", implemented: false },
      { label: "Incidents", href: "/incidents", implemented: false },
      { label: "Reports", href: "/reports", implemented: false },
    ],
  },
  {
    label: "System",
    items: [
      { label: "AI Assistant", href: "/ai-assistant", implemented: false },
      { label: "Administration", href: "/administration", implemented: false },
    ],
  },
];

export default function ShellLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
    } else {
      setReady(true);
    }
  }, [router]);

  if (!ready) return null;

  const current = NAV_GROUPS.flatMap((g) => g.items).find((i) => pathname === i.href);

  return (
    <div className="flex min-h-screen bg-surface-0">
      <aside className="flex w-64 flex-shrink-0 flex-col border-r border-white/[0.06] bg-surface-1">
        <div className="flex items-center gap-2.5 px-5 py-5">
          {/* eslint-disable-next-line @next/next/no-img-element -- a static
              brand asset from /public, not worth next/image's config here */}
          <img src="/bajaj-logo.png" alt="Bajaj Finance" className="h-6 w-auto rounded-sm opacity-95" />
          <div className="min-w-0">
            <h1 className="text-[15px] font-semibold leading-tight tracking-tight text-zinc-50">NetSphere</h1>
            <p className="truncate text-[11px] leading-tight text-zinc-500">Network Platform</p>
          </div>
        </div>

        <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <div className="px-2.5 pb-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-zinc-600">
                {group.label}
              </div>
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const active = pathname === item.href;
                  const Icon = NAV_ICONS[item.href];
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`group flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13.5px] transition-colors ${
                        active
                          ? "bg-indigo-500/15 font-medium text-indigo-300"
                          : "text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-100"
                      }`}
                    >
                      {Icon && (
                        <Icon
                          className={`h-4 w-4 shrink-0 ${active ? "text-indigo-400" : "text-zinc-500 group-hover:text-zinc-300"}`}
                        />
                      )}
                      <span className="min-w-0 flex-1 truncate">{item.label}</span>
                      {!item.implemented && (
                        <span className="shrink-0 rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[9.5px] font-medium text-zinc-500">
                          Soon
                        </span>
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 flex-shrink-0 items-center justify-between gap-4 border-b border-white/[0.06] bg-surface-1/70 px-6 backdrop-blur">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-zinc-200">{current?.label ?? "NetSphere"}</p>
          </div>

          <div className="flex flex-1 items-center justify-end gap-3">
            <label className="relative hidden w-full max-w-xs sm:block">
              <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
              <input
                placeholder="Search…"
                className="w-full rounded-lg border border-white/[0.08] bg-white/[0.03] py-1.5 pl-9 pr-14 text-sm text-zinc-200 placeholder:text-zinc-500 focus:border-indigo-500/50 focus:outline-none focus:ring-1 focus:ring-indigo-500/30"
              />
              <kbd className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-white/[0.08] bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-zinc-500">
                ⌘K
              </kbd>
            </label>

            <button className="relative rounded-lg p-2 text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200">
              <IconBell className="h-[18px] w-[18px]" />
              <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-indigo-400" />
            </button>

            <div className="relative">
              <button
                onClick={() => setMenuOpen((v) => !v)}
                className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 hover:bg-white/[0.05]"
              >
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-xs font-semibold text-white">
                  AD
                </span>
                <IconChevronDown className="h-3.5 w-3.5 text-zinc-500" />
              </button>
              {menuOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                  <div className="animate-fade-in absolute right-0 z-20 mt-2 w-48 rounded-xl border border-white/[0.08] bg-surface-2 p-1.5 shadow-elevated">
                    <div className="px-2.5 py-1.5">
                      <p className="text-sm font-medium text-zinc-100">Admin</p>
                      <p className="truncate text-xs text-zinc-500">admin@netsphere.local</p>
                    </div>
                    <div className="my-1 h-px bg-white/[0.06]" />
                    <button
                      onClick={() => {
                        clearToken();
                        router.replace("/login");
                      }}
                      className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm text-zinc-300 hover:bg-white/[0.06]"
                    >
                      <IconLogout className="h-4 w-4 text-zinc-500" />
                      Sign out
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </div>
    </div>
  );
}
