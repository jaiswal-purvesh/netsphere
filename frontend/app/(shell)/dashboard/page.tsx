"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Summary = {
  total_networks: number;
  networks_by_provider: Record<string, number>;
  total_subnets: number;
  total_devices: number;
  devices_by_type: Record<string, number>;
  vpn_tunnels: number | null;
  bgp_sessions: number | null;
  firewalls: number | null;
  network_incidents: number | null;
  configuration_drift: number | null;
  policy_violations: number | null;
};

function StatCard({ label, value }: { label: string; value: number | string | null }) {
  return (
    <div className="group rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card transition-colors hover:border-white/[0.14]">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="mt-1.5 font-mono text-2xl font-semibold tracking-tight text-zinc-50">
        {value ?? <span className="text-zinc-600">N/A</span>}
      </p>
    </div>
  );
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Summary>("/dashboard/summary")
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? String(e.detail) : "failed to load"));
  }, []);

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight text-zinc-50">Network Overview</h1>
      <p className="mb-6 text-sm text-zinc-500">Global view — cloud/environment/account filters land with multi-tenancy (Phase 10)</p>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {summary && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            <StatCard label="Total Networks" value={summary.total_networks} />
            <StatCard label="Total Subnets" value={summary.total_subnets} />
            <StatCard label="AWS VPCs" value={summary.networks_by_provider.aws} />
            <StatCard label="Azure VNets" value={summary.networks_by_provider.azure} />
            <StatCard label="GCP VPCs" value={summary.networks_by_provider.gcp} />
            <StatCard label="OCI VCNs" value={summary.networks_by_provider.oci} />
            <StatCard label="On-Prem Networks" value={summary.networks_by_provider.onprem} />
          </div>

          <h2 className="mb-2 text-sm font-semibold text-zinc-300">Network Inventory</h2>
          <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            <StatCard label="Total Devices" value={summary.total_devices} />
            <StatCard label="Routers" value={summary.devices_by_type.router} />
            <StatCard label="Switches" value={summary.devices_by_type.switch} />
            <StatCard label="Firewalls (inventory)" value={summary.devices_by_type.firewall} />
          </div>

          <h2 className="mb-2 text-sm font-semibold text-zinc-300">
            Not implemented yet (Phases 4-8)
          </h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            <StatCard label="VPN Tunnels" value={summary.vpn_tunnels} />
            <StatCard label="BGP Sessions" value={summary.bgp_sessions} />
            <StatCard label="Firewalls" value={summary.firewalls} />
            <StatCard label="Network Incidents" value={summary.network_incidents} />
            <StatCard label="Configuration Drift" value={summary.configuration_drift} />
            <StatCard label="Policy Violations" value={summary.policy_violations} />
          </div>
        </>
      )}
    </div>
  );
}
