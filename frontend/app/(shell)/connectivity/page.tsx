"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

// Phase 8 — Connectivity. The `vpn_connections`/`bgp_sessions`/`circuits`/
// `connectivity_links` quartet docs/ERD.md reserved for "VPN/DX/ER/
// Interconnect/FastConnect monitoring," built around the real hybrid
// network this platform models: each cloud reaches on-prem over its own
// dedicated interconnect (AWS Direct Connect, Azure ExpressRoute, GCP
// Cloud Interconnect, OCI FastConnect) riding an MPLS backbone with
// VRF-based segmentation — not a flat shared network. A circuit's
// cloud-side and on-prem-side rows are independently discovered (see
// app/services/connectivity.py's docstring) even though a matched pair
// describes one real physical link.

type BgpSession = {
  id: string;
  circuit_id: string;
  local_asn: number;
  peer_asn: number;
  local_ip: string | null;
  peer_ip: string | null;
  state: "established" | "idle" | "down";
  source: "manual" | "discovered";
  external_id: string | null;
};

type ConnectivityLink = {
  id: string;
  network_id: string;
  network_name: string;
  status: "active" | "pending" | "down";
  source: "manual" | "discovered";
};

type Circuit = {
  id: string;
  owner_type: "cloud_account" | "device";
  owner_id: string;
  owner_label: string;
  circuit_type: "direct_connect" | "expressroute" | "interconnect" | "fastconnect" | "mpls";
  name: string;
  vrf: string | null;
  bandwidth_mbps: number | null;
  location: string | null;
  status: "active" | "provisioning" | "down" | "decommissioned";
  source: "manual" | "discovered";
  external_id: string | null;
  notes: string | null;
  bgp_sessions: BgpSession[];
  links: ConnectivityLink[];
};

type VpnConnection = {
  id: string;
  network_id: string | null;
  network_name: string | null;
  device_id: string | null;
  device_hostname: string | null;
  peer_ip: string | null;
  status: "up" | "down" | "degraded";
  source: "manual" | "discovered";
  external_id: string | null;
  notes: string | null;
};

const CIRCUIT_TYPE_LABEL: Record<string, string> = {
  direct_connect: "AWS Direct Connect",
  expressroute: "Azure ExpressRoute",
  interconnect: "GCP Cloud Interconnect",
  fastconnect: "OCI FastConnect",
  mpls: "On-prem MPLS",
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
    active: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30",
    established: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30",
    up: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30",
    provisioning: "bg-amber-500/10 text-amber-400 ring-amber-500/30",
    pending: "bg-amber-500/10 text-amber-400 ring-amber-500/30",
    degraded: "bg-amber-500/10 text-amber-400 ring-amber-500/30",
    idle: "bg-amber-500/10 text-amber-400 ring-amber-500/30",
    down: "bg-red-500/10 text-red-400 ring-red-500/30",
    decommissioned: "bg-white/[0.06] text-zinc-500 ring-white/[0.1]",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ring-inset ${
        styles[status] ?? "bg-white/[0.06] text-zinc-400 ring-white/[0.1]"
      }`}
    >
      {status}
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

export default function ConnectivityPage() {
  const [circuits, setCircuits] = useState<Circuit[]>([]);
  const [vpnConnections, setVpnConnections] = useState<VpnConnection[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  function load(query?: string) {
    api
      .get<Circuit[]>(`/connectivity/circuits${query ? `?q=${encodeURIComponent(query)}` : ""}`)
      .then(setCircuits)
      .catch((e) => setError(e instanceof ApiError ? String(e.detail) : "failed to load circuits"));
    api.get<VpnConnection[]>("/connectivity/vpn-connections").then(setVpnConnections).catch(() => undefined);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cloudCircuits = circuits.filter((c) => c.owner_type === "cloud_account");
  const onPremCircuits = circuits.filter((c) => c.owner_type === "device");
  const totalBandwidth = circuits.reduce((n, c) => n + (c.bandwidth_mbps ?? 0), 0);
  const downCircuits = circuits.filter((c) => c.status === "down" || c.status === "decommissioned").length;

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-50">Connectivity</h1>
          <p className="mt-1 max-w-3xl text-sm text-zinc-500">
            Dedicated interconnects (AWS Direct Connect, Azure ExpressRoute, GCP Cloud Interconnect, OCI FastConnect)
            and their on-prem MPLS/VRF handoffs, each with the BGP session carrying routes across it — plus IPsec
            site-to-site VPNs used as a backup path. Cloud-side and on-prem-side circuits are discovered
            independently; a matched pair describes the two ends of one physical link.
          </p>
        </div>
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            load(e.target.value);
          }}
          placeholder="search circuit name…"
          className="w-64 rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600"
        />
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Circuits" value={circuits.length} />
        <StatCard label="Total bandwidth" value={`${totalBandwidth.toLocaleString()} Mbps`} />
        <StatCard label="Down/decommissioned" value={downCircuits} />
        <StatCard label="VPN connections" value={vpnConnections.length} />
      </div>

      <div className="mb-6">
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">Cloud-side circuits</h2>
        {cloudCircuits.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/[0.08] bg-surface-2 p-8 text-sm text-zinc-500">
            No cloud-side circuits yet — they populate automatically the next time cloud discovery runs (IPAM → a
            cloud account → Sync/Discover).
          </div>
        ) : (
          <div className="space-y-3">
            {cloudCircuits.map((c) => {
              const isOpen = expanded[c.id] ?? false;
              return (
                <div key={c.id} className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
                  <button
                    onClick={() => setExpanded((e) => ({ ...e, [c.id]: !isOpen }))}
                    className="flex w-full flex-wrap items-center justify-between gap-2 text-left"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-medium text-zinc-100">{c.name}</h3>
                        <span className="rounded-full bg-indigo-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-indigo-300 ring-1 ring-inset ring-indigo-500/30">
                          {CIRCUIT_TYPE_LABEL[c.circuit_type] ?? c.circuit_type}
                        </span>
                        <StatusBadge status={c.status} />
                        <SourceBadge source={c.source} />
                      </div>
                      <p className="mt-0.5 text-xs text-zinc-500">
                        {c.owner_label} · {c.vrf ?? "no VRF"} · {c.bandwidth_mbps ? `${c.bandwidth_mbps} Mbps` : "—"} ·{" "}
                        {c.location ?? "location unknown"}
                        {c.links.length > 0 && ` · attaches ${c.links.map((l) => l.network_name).join(", ")}`}
                      </p>
                    </div>
                    <span className="text-xs text-zinc-500">{isOpen ? "Hide BGP ▲" : "Show BGP ▼"}</span>
                  </button>
                  {isOpen && (
                    <div className="mt-3 overflow-x-auto border-t border-white/[0.06] pt-3">
                      {c.bgp_sessions.length === 0 ? (
                        <p className="text-xs text-zinc-500">No BGP session recorded.</p>
                      ) : (
                        <table className="w-full text-left text-xs">
                          <thead>
                            <tr className="text-zinc-500">
                              <th className="pb-1 pr-4 font-medium">Local ASN</th>
                              <th className="pb-1 pr-4 font-medium">Peer ASN</th>
                              <th className="pb-1 pr-4 font-medium">Local IP</th>
                              <th className="pb-1 pr-4 font-medium">Peer IP</th>
                              <th className="pb-1 font-medium">State</th>
                            </tr>
                          </thead>
                          <tbody>
                            {c.bgp_sessions.map((s) => (
                              <tr key={s.id} className="border-t border-white/[0.04]">
                                <td className="py-1 pr-4 font-mono text-zinc-200">{s.local_asn}</td>
                                <td className="py-1 pr-4 font-mono text-zinc-200">{s.peer_asn}</td>
                                <td className="py-1 pr-4 font-mono text-zinc-400">{s.local_ip ?? "—"}</td>
                                <td className="py-1 pr-4 font-mono text-zinc-400">{s.peer_ip ?? "—"}</td>
                                <td className="py-1">
                                  <StatusBadge status={s.state} />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="mb-6">
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">On-prem MPLS handoffs</h2>
        {onPremCircuits.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/[0.08] bg-surface-2 p-8 text-sm text-zinc-500">
            No on-prem circuits yet — they populate automatically the next time device discovery runs.
          </div>
        ) : (
          <div className="space-y-3">
            {onPremCircuits.map((c) => {
              const isOpen = expanded[c.id] ?? false;
              return (
                <div key={c.id} className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
                  <button
                    onClick={() => setExpanded((e) => ({ ...e, [c.id]: !isOpen }))}
                    className="flex w-full flex-wrap items-center justify-between gap-2 text-left"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-medium text-zinc-100">{c.name}</h3>
                        <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-400">
                          {CIRCUIT_TYPE_LABEL[c.circuit_type] ?? c.circuit_type}
                        </span>
                        <StatusBadge status={c.status} />
                        <SourceBadge source={c.source} />
                      </div>
                      <p className="mt-0.5 text-xs text-zinc-500">
                        {c.owner_label} · {c.vrf ?? "no VRF"} · {c.bandwidth_mbps ? `${c.bandwidth_mbps} Mbps` : "—"} ·{" "}
                        {c.location ?? "location unknown"}
                      </p>
                    </div>
                    <span className="text-xs text-zinc-500">{isOpen ? "Hide BGP ▲" : "Show BGP ▼"}</span>
                  </button>
                  {isOpen && (
                    <div className="mt-3 overflow-x-auto border-t border-white/[0.06] pt-3">
                      {c.bgp_sessions.length === 0 ? (
                        <p className="text-xs text-zinc-500">No BGP session recorded.</p>
                      ) : (
                        <table className="w-full text-left text-xs">
                          <thead>
                            <tr className="text-zinc-500">
                              <th className="pb-1 pr-4 font-medium">Local ASN</th>
                              <th className="pb-1 pr-4 font-medium">Peer ASN</th>
                              <th className="pb-1 pr-4 font-medium">Local IP</th>
                              <th className="pb-1 pr-4 font-medium">Peer IP</th>
                              <th className="pb-1 font-medium">State</th>
                            </tr>
                          </thead>
                          <tbody>
                            {c.bgp_sessions.map((s) => (
                              <tr key={s.id} className="border-t border-white/[0.04]">
                                <td className="py-1 pr-4 font-mono text-zinc-200">{s.local_asn}</td>
                                <td className="py-1 pr-4 font-mono text-zinc-200">{s.peer_asn}</td>
                                <td className="py-1 pr-4 font-mono text-zinc-400">{s.local_ip ?? "—"}</td>
                                <td className="py-1 pr-4 font-mono text-zinc-400">{s.peer_ip ?? "—"}</td>
                                <td className="py-1">
                                  <StatusBadge status={s.state} />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">VPN connections</h2>
        {vpnConnections.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/[0.08] bg-surface-2 p-8 text-sm text-zinc-500">
            No IPsec VPN connections recorded — most networks here reach on-prem only via a dedicated circuit above.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-white/[0.08] bg-surface-2 shadow-card">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-zinc-500">
                  <th className="p-3 font-medium">Attached to</th>
                  <th className="p-3 font-medium">Peer IP</th>
                  <th className="p-3 font-medium">Status</th>
                  <th className="p-3 font-medium">Source</th>
                  <th className="p-3 font-medium">External ID</th>
                </tr>
              </thead>
              <tbody>
                {vpnConnections.map((v) => (
                  <tr key={v.id} className="border-t border-white/[0.04]">
                    <td className="p-3 font-medium text-zinc-200">{v.network_name ?? v.device_hostname ?? "—"}</td>
                    <td className="p-3 font-mono text-zinc-400">{v.peer_ip ?? "—"}</td>
                    <td className="p-3">
                      <StatusBadge status={v.status} />
                    </td>
                    <td className="p-3">
                      <SourceBadge source={v.source} />
                    </td>
                    <td className="p-3 font-mono text-zinc-500">{v.external_id ?? "—"}</td>
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
