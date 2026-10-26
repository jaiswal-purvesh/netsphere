"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

// Phase 3 — Cloud Networks. The `network_interfaces` table docs/ERD.md
// reserved for this phase (ENIs/NICs discovered per cloud, pulled in by the
// same discovery sweep that already populates IPAM/Routing) plus a
// deliberate extension: VPC/VNet/VCN peering connections as first-class
// objects, not just implied by a `vpc_peering` route target (see Routing).
// This is inventory, same "additive on top of network/subnet discovery"
// contract as Routing's own tables — not a security-group rule engine
// (Phase 6's job, see app/models/cloud_networks.py's docstring).

type CloudNetworkInterface = {
  id: string;
  subnet_id: string;
  subnet_cidr: string;
  network_id: string;
  network_name: string;
  name: string;
  private_ip: string | null;
  public_ip: string | null;
  attached_to: string | null;
  status: "in_use" | "available";
  security_groups: string[];
  source: "manual" | "discovered";
  external_id: string | null;
  notes: string | null;
};

type NetworkPeering = {
  id: string;
  network_a_id: string;
  network_a_name: string;
  network_b_id: string;
  network_b_name: string;
  status: "active" | "pending" | "rejected" | "expired";
  source: "manual" | "discovered";
  external_id: string | null;
  notes: string | null;
};

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="mt-1.5 font-mono text-2xl font-semibold tracking-tight text-zinc-50">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    in_use: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30",
    available: "bg-white/[0.06] text-zinc-400 ring-white/[0.1]",
    active: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30",
    pending: "bg-amber-500/10 text-amber-400 ring-amber-500/30",
    rejected: "bg-red-500/10 text-red-400 ring-red-500/30",
    expired: "bg-white/[0.06] text-zinc-500 ring-white/[0.1]",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ring-inset ${
        styles[status] ?? "bg-white/[0.06] text-zinc-400 ring-white/[0.1]"
      }`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

function SourceBadge({ source }: { source: string }) {
  return (
    <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-400">
      {source}
    </span>
  );
}

export default function CloudNetworksPage() {
  const [interfaces, setInterfaces] = useState<CloudNetworkInterface[]>([]);
  const [peerings, setPeerings] = useState<NetworkPeering[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  function load(query?: string) {
    api
      .get<CloudNetworkInterface[]>(`/cloud-networks/interfaces${query ? `?q=${encodeURIComponent(query)}` : ""}`)
      .then(setInterfaces)
      .catch((e) => setError(e instanceof ApiError ? String(e.detail) : "failed to load interfaces"));
    api.get<NetworkPeering[]>("/cloud-networks/peerings").then(setPeerings).catch(() => undefined);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const interfacesByNetwork = interfaces.reduce<Record<string, { networkName: string; items: CloudNetworkInterface[] }>>(
    (acc, iface) => {
      const bucket = acc[iface.network_id] ?? { networkName: iface.network_name, items: [] };
      bucket.items.push(iface);
      acc[iface.network_id] = bucket;
      return acc;
    },
    {},
  );
  const networkGroups = Object.entries(interfacesByNetwork).sort((a, b) => a[1].networkName.localeCompare(b[1].networkName));

  const publicIpCount = interfaces.filter((i) => i.public_ip).length;
  const activePeerings = peerings.filter((p) => p.status === "active").length;

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-50">Cloud Networks</h1>
          <p className="mt-1 max-w-3xl text-sm text-zinc-500">
            ENIs/NICs/VNICs discovered per cloud, grouped by network, plus the VPC/VNet/VCN peering connections between
            them — the same discovery sweep that already populates IPAM and Routing. This is inventory, not a
            security-group rule engine — see Phase 6 for normalized firewall/security-group policy.
          </p>
        </div>
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            load(e.target.value);
          }}
          placeholder="search interface name…"
          className="w-64 rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600"
        />
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Interfaces" value={interfaces.length} />
        <StatCard label="Networks with interfaces" value={networkGroups.length} />
        <StatCard label="With a public IP" value={publicIpCount} />
        <StatCard label="Active peerings" value={activePeerings} />
      </div>

      <div className="mb-6">
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">Interfaces by network</h2>
        {networkGroups.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/[0.08] bg-surface-2 p-8 text-sm text-zinc-500">
            No interfaces yet — they populate automatically the next time cloud discovery runs (IPAM → a cloud account
            → Sync/Discover).
          </div>
        ) : (
          <div className="space-y-3">
            {networkGroups.map(([networkId, group]) => {
              const isOpen = expanded[networkId] ?? false;
              return (
                <div key={networkId} className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
                  <button
                    onClick={() => setExpanded((e) => ({ ...e, [networkId]: !isOpen }))}
                    className="flex w-full flex-wrap items-center justify-between gap-2 text-left"
                  >
                    <div>
                      <h3 className="font-medium text-zinc-100">{group.networkName}</h3>
                      <p className="mt-0.5 text-xs text-zinc-500">
                        {group.items.length} interface{group.items.length === 1 ? "" : "s"}
                      </p>
                    </div>
                    <span className="text-xs text-zinc-500">{isOpen ? "Hide interfaces ▲" : "Show interfaces ▼"}</span>
                  </button>
                  {isOpen && (
                    <div className="mt-3 overflow-x-auto border-t border-white/[0.06] pt-3">
                      <table className="w-full text-left text-xs">
                        <thead>
                          <tr className="text-zinc-500">
                            <th className="pb-1 pr-4 font-medium">Name</th>
                            <th className="pb-1 pr-4 font-medium">Subnet</th>
                            <th className="pb-1 pr-4 font-medium">Private IP</th>
                            <th className="pb-1 pr-4 font-medium">Public IP</th>
                            <th className="pb-1 pr-4 font-medium">Attached to</th>
                            <th className="pb-1 pr-4 font-medium">Security groups</th>
                            <th className="pb-1 pr-4 font-medium">Status</th>
                            <th className="pb-1 font-medium">Source</th>
                          </tr>
                        </thead>
                        <tbody>
                          {group.items.map((iface) => (
                            <tr key={iface.id} className="border-t border-white/[0.04]">
                              <td className="py-1 pr-4 font-mono text-zinc-200">{iface.name}</td>
                              <td className="py-1 pr-4 font-mono text-zinc-400">{iface.subnet_cidr}</td>
                              <td className="py-1 pr-4 font-mono text-zinc-300">{iface.private_ip ?? "—"}</td>
                              <td className="py-1 pr-4 font-mono text-zinc-300">{iface.public_ip ?? "—"}</td>
                              <td className="py-1 pr-4 text-zinc-400">{iface.attached_to ?? "—"}</td>
                              <td className="py-1 pr-4 text-zinc-400">
                                {iface.security_groups.length ? iface.security_groups.join(", ") : "—"}
                              </td>
                              <td className="py-1 pr-4">
                                <StatusBadge status={iface.status} />
                              </td>
                              <td className="py-1">
                                <SourceBadge source={iface.source} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">Peering connections</h2>
        {peerings.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/[0.08] bg-surface-2 p-8 text-sm text-zinc-500">
            No peering connections yet — most providers here have none by design (peering-heavy demo data lives on the
            AWS mock; GCP&apos;s routes-based model has no first-class peering object at all).
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-white/[0.08] bg-surface-2 shadow-card">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-zinc-500">
                  <th className="p-3 font-medium">Network A</th>
                  <th className="p-3 font-medium">Network B</th>
                  <th className="p-3 font-medium">Status</th>
                  <th className="p-3 font-medium">Source</th>
                  <th className="p-3 font-medium">External ID</th>
                </tr>
              </thead>
              <tbody>
                {peerings.map((p) => (
                  <tr key={p.id} className="border-t border-white/[0.04]">
                    <td className="p-3 font-medium text-zinc-200">{p.network_a_name}</td>
                    <td className="p-3 font-medium text-zinc-200">{p.network_b_name}</td>
                    <td className="p-3">
                      <StatusBadge status={p.status} />
                    </td>
                    <td className="p-3">
                      <SourceBadge source={p.source} />
                    </td>
                    <td className="p-3 font-mono text-zinc-500">{p.external_id ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
