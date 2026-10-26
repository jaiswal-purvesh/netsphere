"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

// Phase 5 — Path Analyzer. The read-only "would this traffic be allowed
// today?" check called out in claude/firewall-policy-automation-design.md
// §3.8 as the single highest-value, lowest-risk thing to ship first ("Ship
// it first") — it needs no write access to any firewall, just a live read
// of the current rulebase. See backend app/services/path_analyzer.py for
// the resolution/verdict logic: every verdict here comes from a real check
// against a real device's current rulebase (fw_panorama_adapter +
// fw_redundancy, the same primitives Policy Optimizer already uses), never
// a guess — a hop with no matching credentialed integration reports
// "unknown", not a fabricated allow/block.

type NetworkRef = { id: string; name: string; cidr: string };

type Hop = {
  firewall: string;
  integration_id: string | null;
  verdict: "allowed" | "blocked" | "not_currently_allowed" | "unknown";
  covering_rule: string | null;
  blocking_rule: string | null;
  notes: string[];
  error: string | null;
};

type SimulationResult = {
  id: string;
  source: string;
  destination: string;
  protocol: string;
  port_low: number;
  port_high: number;
  source_network: NetworkRef | null;
  destination_network: NetworkRef | null;
  hops: Hop[];
  overall_verdict: "allowed" | "blocked" | "not_currently_allowed" | "unknown";
  notes: string[];
  created_at: string;
};

const VERDICT_STYLE: Record<string, string> = {
  allowed: "bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/30",
  blocked: "bg-red-500/10 text-red-400 ring-1 ring-inset ring-red-500/30",
  not_currently_allowed: "bg-amber-500/10 text-amber-400 ring-1 ring-inset ring-amber-500/30",
  unknown: "bg-white/[0.06] text-zinc-400 ring-1 ring-inset ring-white/[0.1]",
};

const VERDICT_LABEL: Record<string, string> = {
  allowed: "Allowed",
  blocked: "Blocked",
  not_currently_allowed: "Not currently allowed",
  unknown: "Unknown",
};

function VerdictBadge({ verdict }: { verdict: string }) {
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${VERDICT_STYLE[verdict] ?? VERDICT_STYLE.unknown}`}>
      {VERDICT_LABEL[verdict] ?? verdict}
    </span>
  );
}

const emptyForm = { source: "", destination: "", protocol: "tcp", port: "443" };

export default function PathAnalyzerPage() {
  const [form, setForm] = useState(emptyForm);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [runs, setRuns] = useState<SimulationResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function loadRuns() {
    api.get<SimulationResult[]>("/path/runs").then(setRuns).catch(() => undefined);
  }

  useEffect(() => {
    loadRuns();
  }, []);

  async function runSimulation() {
    setError(null);
    setBusy(true);
    try {
      const payload = {
        source: form.source.trim(),
        destination: form.destination.trim(),
        protocol: form.protocol,
        port: parseInt(form.port, 10) || undefined,
      };
      const res = await api.post<SimulationResult>("/path/simulate", payload);
      setResult(res);
      loadRuns();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "simulation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-zinc-50">Path Analyzer</h1>
        <p className="mt-1 max-w-3xl text-sm text-zinc-500">
          Checks whether traffic between a source and destination would be allowed today, by resolving each side to a
          known network, finding any firewall recorded against it, and pulling that firewall&apos;s live rulebase.
          Nothing here is simulated data — an unreachable device or an unmatched integration reports as{" "}
          <span className="text-zinc-300">unknown</span>, not a guessed allow or block.
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      <div className="mb-6 rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">Check a path</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-56">
            <label className="mb-1 block text-xs font-medium text-zinc-500">Source</label>
            <input
              value={form.source}
              onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}
              placeholder="10.20.4.15 or 10.20.4.0/24"
              className="w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600"
            />
          </div>
          <div className="w-56">
            <label className="mb-1 block text-xs font-medium text-zinc-500">Destination</label>
            <input
              value={form.destination}
              onChange={(e) => setForm((f) => ({ ...f, destination: e.target.value }))}
              placeholder="10.21.0.10"
              className="w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600"
            />
          </div>
          <div className="w-28">
            <label className="mb-1 block text-xs font-medium text-zinc-500">Protocol</label>
            <select
              value={form.protocol}
              onChange={(e) => setForm((f) => ({ ...f, protocol: e.target.value }))}
              className="w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200"
            >
              <option value="tcp">TCP</option>
              <option value="udp">UDP</option>
              <option value="icmp">ICMP</option>
            </select>
          </div>
          <div className="w-24">
            <label className="mb-1 block text-xs font-medium text-zinc-500">Port</label>
            <input
              value={form.port}
              onChange={(e) => setForm((f) => ({ ...f, port: e.target.value }))}
              className="w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200"
            />
          </div>
          <button
            onClick={runSimulation}
            disabled={busy || !form.source.trim() || !form.destination.trim()}
            className="rounded-lg bg-indigo-500 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-indigo-400 disabled:opacity-50"
          >
            {busy ? "Checking…" : "Check path"}
          </button>
        </div>
      </div>

      {result && (
        <div className="mb-6 rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-zinc-200">
                {result.source} → {result.destination}{" "}
                <span className="font-normal text-zinc-500">
                  ({result.protocol.toUpperCase()}/{result.port_low === result.port_high ? result.port_low : `${result.port_low}-${result.port_high}`})
                </span>
              </h2>
              <p className="mt-0.5 text-xs text-zinc-500">
                {result.source_network ? `${result.source_network.name} (${result.source_network.cidr})` : "no matching network"}
                {" → "}
                {result.destination_network
                  ? `${result.destination_network.name} (${result.destination_network.cidr})`
                  : "no matching network"}
              </p>
            </div>
            <VerdictBadge verdict={result.overall_verdict} />
          </div>

          {result.notes.length > 0 && (
            <ul className="mb-3 space-y-1 text-xs text-zinc-500">
              {result.notes.map((n, idx) => (
                <li key={idx}>{n}</li>
              ))}
            </ul>
          )}

          {result.hops.length === 0 ? (
            <p className="text-sm text-zinc-500">No firewall hop sits in this path.</p>
          ) : (
            <div className="space-y-2 border-t border-white/[0.06] pt-3">
              {result.hops.map((h, idx) => (
                <div key={idx} className="rounded-lg border border-white/[0.06] bg-surface-1 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium text-zinc-200">{h.firewall}</span>
                    <VerdictBadge verdict={h.verdict} />
                  </div>
                  <div className="mt-1 space-y-0.5 text-xs text-zinc-500">
                    {h.covering_rule && <p>Covering rule: <span className="font-mono text-zinc-400">{h.covering_rule}</span></p>}
                    {h.blocking_rule && <p>Blocking rule: <span className="font-mono text-zinc-400">{h.blocking_rule}</span></p>}
                    {h.error && <p className="text-red-400">{h.error}</p>}
                    {h.notes.map((n, ni) => (
                      <p key={ni}>{n}</p>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">Recent checks</h2>
        {runs.length === 0 ? (
          <p className="text-sm text-zinc-500">No path checks run yet.</p>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-surface-2">
                <tr className="text-xs uppercase tracking-wide text-zinc-500">
                  <th className="pb-2 pr-4 font-medium">When</th>
                  <th className="pb-2 pr-4 font-medium">Source</th>
                  <th className="pb-2 pr-4 font-medium">Destination</th>
                  <th className="pb-2 pr-4 font-medium">Service</th>
                  <th className="pb-2 pr-4 font-medium">Hops</th>
                  <th className="pb-2 font-medium">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="border-t border-white/[0.06]">
                    <td className="py-1.5 pr-4 text-zinc-500">{new Date(r.created_at).toLocaleString()}</td>
                    <td className="py-1.5 pr-4 font-mono text-xs text-zinc-300">{r.source}</td>
                    <td className="py-1.5 pr-4 font-mono text-xs text-zinc-300">{r.destination}</td>
                    <td className="py-1.5 pr-4 text-zinc-400">
                      {r.protocol.toUpperCase()}/{r.port_low === r.port_high ? r.port_low : `${r.port_low}-${r.port_high}`}
                    </td>
                    <td className="py-1.5 pr-4 text-zinc-400">{r.hops.length}</td>
                    <td className="py-1.5">
                      <VerdictBadge verdict={r.overall_verdict} />
                    </td>
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
