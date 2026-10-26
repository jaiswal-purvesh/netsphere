"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

// Phase 3 — Routing. The other half of "network source of truth" the
// spec called for alongside IPAM and device/interface inventory: what's
// routing where, cloud side (a route table per network, pulled in by the
// same discovery sweep that already populates IPAM — see
// app/services/routing.py) and on-prem side (a device's own static
// routes, from the SNMP sweep). This is inventory, not path computation —
// Path Analyzer's own multi-hop follow-up is what would consume this data
// for real route-aware reachability checks.

type Route = {
  id: string;
  route_table_id: string | null;
  device_id: string | null;
  destination_cidr: string;
  target_type: string;
  target_ref: string | null;
  state: "active" | "blackhole";
  external_id: string | null;
};

type RouteTable = {
  id: string;
  network_id: string;
  network_name: string;
  network_cidr: string;
  name: string;
  is_main: boolean;
  source: "manual" | "discovered";
  external_id: string | null;
  notes: string | null;
  route_count: number;
  routes: Route[];
};

type DeviceRoutes = {
  device_id: string;
  hostname: string;
  routes: Route[];
};

const TARGET_LABEL: Record<string, string> = {
  local: "Local",
  internet_gateway: "Internet gateway",
  nat_gateway: "NAT gateway",
  vpc_peering: "VPC peering",
  transit_gateway: "Transit gateway",
  vpn_gateway: "VPN gateway",
  virtual_appliance: "Virtual appliance",
  next_hop: "Next hop",
  interface: "Interface",
  instance: "Instance",
  other: "Other",
};

function TargetBadge({ targetType }: { targetType: string }) {
  const isEgress = targetType === "internet_gateway" || targetType === "nat_gateway";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
        isEgress
          ? "bg-amber-500/10 text-amber-400 ring-1 ring-inset ring-amber-500/30"
          : "bg-white/[0.06] text-zinc-400 ring-1 ring-inset ring-white/[0.1]"
      }`}
    >
      {TARGET_LABEL[targetType] ?? targetType}
    </span>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="mt-1.5 font-mono text-2xl font-semibold tracking-tight text-zinc-50">{value}</p>
    </div>
  );
}

function RouteRows({ routes }: { routes: Route[] }) {
  return (
    <table className="w-full text-left text-xs">
      <thead>
        <tr className="text-zinc-500">
          <th className="pb-1 pr-4 font-medium">Destination</th>
          <th className="pb-1 pr-4 font-medium">Target</th>
          <th className="pb-1 pr-4 font-medium">Target ref</th>
          <th className="pb-1 font-medium">State</th>
        </tr>
      </thead>
      <tbody>
        {routes.map((r) => (
          <tr key={r.id} className="border-t border-white/[0.04]">
            <td className="py-1 pr-4 font-mono text-zinc-200">{r.destination_cidr}</td>
            <td className="py-1 pr-4">
              <TargetBadge targetType={r.target_type} />
            </td>
            <td className="py-1 pr-4 font-mono text-zinc-400">{r.target_ref ?? "—"}</td>
            <td className="py-1">
              <span className={r.state === "blackhole" ? "text-red-400" : "text-emerald-400"}>{r.state}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function RoutingPage() {
  const [routeTables, setRouteTables] = useState<RouteTable[]>([]);
  const [deviceRoutes, setDeviceRoutes] = useState<DeviceRoutes[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  function load(query?: string) {
    api
      .get<RouteTable[]>(`/routing/route-tables${query ? `?q=${encodeURIComponent(query)}` : ""}`)
      .then(setRouteTables)
      .catch((e) => setError(e instanceof ApiError ? String(e.detail) : "failed to load route tables"));
    api.get<DeviceRoutes[]>("/routing/device-routes").then(setDeviceRoutes).catch(() => undefined);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalRoutes =
    routeTables.reduce((n, rt) => n + rt.route_count, 0) + deviceRoutes.reduce((n, d) => n + d.routes.length, 0);
  const egressRoutes = [
    ...routeTables.flatMap((rt) => rt.routes),
    ...deviceRoutes.flatMap((d) => d.routes),
  ].filter((r) => r.target_type === "internet_gateway" || r.target_type === "nat_gateway").length;

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-50">Routing</h1>
          <p className="mt-1 max-w-3xl text-sm text-zinc-500">
            What&apos;s routing where — a route table per cloud network (pulled in by the same discovery sweep that
            populates IPAM) plus each on-prem device&apos;s own static routes. This is inventory, not a path check —
            see Path Analyzer for &quot;would this traffic get through.&quot;
          </p>
        </div>
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            load(e.target.value);
          }}
          placeholder="search route table name…"
          className="w-64 rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600"
        />
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Route tables" value={routeTables.length} />
        <StatCard label="Devices with static routes" value={deviceRoutes.length} />
        <StatCard label="Total routes" value={totalRoutes} />
        <StatCard label="Internet/NAT egress routes" value={egressRoutes} />
      </div>

      <div className="mb-6">
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">Cloud route tables</h2>
        {routeTables.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/[0.08] bg-surface-2 p-8 text-sm text-zinc-500">
            No route tables yet — they populate automatically the next time cloud discovery runs (IPAM → a cloud
            account → Sync/Discover).
          </div>
        ) : (
          <div className="space-y-3">
            {routeTables.map((rt) => {
              const isOpen = expanded[rt.id] ?? false;
              return (
                <div key={rt.id} className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
                  <button
                    onClick={() => setExpanded((e) => ({ ...e, [rt.id]: !isOpen }))}
                    className="flex w-full flex-wrap items-center justify-between gap-2 text-left"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-medium text-zinc-100">{rt.name}</h3>
                        {rt.is_main && (
                          <span className="rounded-full bg-indigo-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-indigo-300 ring-1 ring-inset ring-indigo-500/30">
                            main
                          </span>
                        )}
                        <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-400">
                          {rt.source}
                        </span>
                      </div>
                      <p className="mt-0.5 text-xs text-zinc-500">
                        {rt.network_name} ({rt.network_cidr}) · {rt.route_count} route{rt.route_count === 1 ? "" : "s"}
                      </p>
                    </div>
                    <span className="text-xs text-zinc-500">{isOpen ? "Hide routes ▲" : "Show routes ▼"}</span>
                  </button>
                  {isOpen && (
                    <div className="mt-3 overflow-x-auto border-t border-white/[0.06] pt-3">
                      {rt.routes.length === 0 ? (
                        <p className="text-xs text-zinc-500">No routes recorded.</p>
                      ) : (
                        <RouteRows routes={rt.routes} />
                      )}
                      {rt.notes && <p className="mt-2 text-xs text-zinc-600">{rt.notes}</p>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">On-prem device static routes</h2>
        {deviceRoutes.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/[0.08] bg-surface-2 p-8 text-sm text-zinc-500">
            No devices with static routes yet — most switches have none (L2 devices don&apos;t route); routers and
            firewalls populate this from the SNMP discovery sweep.
          </div>
        ) : (
          <div className="space-y-3">
            {deviceRoutes.map((d) => {
              const key = `dev:${d.device_id}`;
              const isOpen = expanded[key] ?? false;
              return (
                <div key={d.device_id} className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
                  <button
                    onClick={() => setExpanded((e) => ({ ...e, [key]: !isOpen }))}
                    className="flex w-full flex-wrap items-center justify-between gap-2 text-left"
                  >
                    <div>
                      <h3 className="font-medium text-zinc-100">{d.hostname}</h3>
                      <p className="mt-0.5 text-xs text-zinc-500">
                        {d.routes.length} route{d.routes.length === 1 ? "" : "s"}
                      </p>
                    </div>
                    <span className="text-xs text-zinc-500">{isOpen ? "Hide routes ▲" : "Show routes ▼"}</span>
                  </button>
                  {isOpen && (
                    <div className="mt-3 overflow-x-auto border-t border-white/[0.06] pt-3">
                      <RouteRows routes={d.routes} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
