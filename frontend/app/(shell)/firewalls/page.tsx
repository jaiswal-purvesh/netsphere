"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

// Policy Optimizer / Firewall Analyzer — Phase 6, converges with
// claude/firewall-policy-automation-design.md. This is the whole-rulebase
// hygiene capability FireMon (Policy Analyzer), Tufin (SecureTrack), and
// AlgoSec (Firewall Analyzer) all lead with: pull the live rulebase from a
// Panorama/PAN-OS integration, flag any-any / overly-permissive / shadowed /
// duplicate / disabled rules, and track a lightweight review workflow
// (owner + note) per rule across analysis runs. Every finding here comes
// from a real device call (app/services/fw_panorama_adapter.fetch_rulebase
// on the backend) — an unreachable device surfaces as an error, never a
// fabricated result.

type IntegrationOption = { id: string; name: string; vendor: string };

type Finding = { rule: string; category: string; severity: "critical" | "warn" | "info"; message: string; related_rule: string | null };

type AnalysisRun = {
  id: string;
  integration_id: string;
  integration_name: string;
  device_group: string | null;
  status: "ok" | "error";
  error_message: string;
  rule_count: number;
  severity_counts: Record<string, number>;
  findings: Finding[];
  created_at: string;
};

type RuleRecord = {
  id: string;
  integration_id: string;
  integration_name: string;
  device_group: string | null;
  rule_name: string;
  action: string;
  disabled: boolean;
  source_cidrs: string[];
  destination_cidrs: string[];
  services: { proto: string; port_low?: number; port_high?: number }[];
  first_seen_at: string;
  last_seen_at: string;
  removed_at: string | null;
  findings: Finding[];
  owner: string;
  last_reviewed_at: string | null;
  review_note: string;
};

const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-red-500/10 text-red-400 ring-1 ring-inset ring-red-500/30",
  warn: "bg-amber-500/10 text-amber-400 ring-1 ring-inset ring-amber-500/30",
  info: "bg-white/[0.06] text-zinc-400 ring-1 ring-inset ring-white/[0.1]",
};

const CATEGORY_LABEL: Record<string, string> = {
  any_any: "Any / Any / Any",
  overly_permissive: "Overly permissive",
  shadowed: "Shadowed",
  duplicate: "Duplicate",
  disabled: "Disabled",
};

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.info}`}>
      {severity}
    </span>
  );
}

function StatCard({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className={`mt-1.5 font-mono text-2xl font-semibold tracking-tight ${tone ?? "text-zinc-50"}`}>{value}</p>
    </div>
  );
}

export default function FirewallsPage() {
  const [integrations, setIntegrations] = useState<IntegrationOption[]>([]);
  const [selectedIntegration, setSelectedIntegration] = useState("");
  const [deviceGroup, setDeviceGroup] = useState("");
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [rules, setRules] = useState<RuleRecord[]>([]);
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<RuleRecord | null>(null);
  const [reviewForm, setReviewForm] = useState({ owner: "", review_note: "" });

  function loadAll() {
    api.get<IntegrationOption[]>("/firewalls/integrations").then(setIntegrations).catch(() => undefined);
    api.get<AnalysisRun[]>("/firewalls/runs").then(setRuns).catch(() => undefined);
    api
      .get<RuleRecord[]>(`/firewalls/rules${severityFilter ? `?severity=${severityFilter}` : ""}`)
      .then(setRules)
      .catch(() => undefined);
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [severityFilter]);

  async function runAnalysis() {
    if (!selectedIntegration) return;
    setAnalyzing(true);
    setError(null);
    try {
      await api.post<AnalysisRun>("/firewalls/analyze", {
        integration_id: selectedIntegration,
        device_group: deviceGroup || null,
      });
      loadAll();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "analysis failed");
      loadAll(); // the failed run is still recorded — refresh history to show it
    } finally {
      setAnalyzing(false);
    }
  }

  async function submitReview() {
    if (!reviewing) return;
    try {
      await api.post<RuleRecord>(`/firewalls/rules/${reviewing.id}/review`, reviewForm);
      setReviewing(null);
      loadAll();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "review failed");
    }
  }

  const latestRun = runs[0];
  const totals = rules.reduce(
    (acc, r) => {
      for (const f of r.findings) acc[f.severity] = (acc[f.severity] ?? 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-50">Policy Optimizer</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Pulls the live rulebase from a Panorama/PAN-OS integration and flags any-any, overly-permissive, shadowed,
            duplicate, and disabled rules — the same cleanup queue FireMon, Tufin, and AlgoSec build their audits around.
          </p>
        </div>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Rules tracked" value={rules.length} />
        <StatCard label="Critical findings" value={totals.critical ?? 0} tone={totals.critical ? "text-red-400" : undefined} />
        <StatCard label="Warnings" value={totals.warn ?? 0} tone={totals.warn ? "text-amber-400" : undefined} />
        <StatCard label="Last analyzed" value={latestRun ? new Date(latestRun.created_at).toLocaleString() : "never"} />
      </div>

      <div className="mb-6 rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">Run analysis</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-500">Integration</label>
            <select
              value={selectedIntegration}
              onChange={(e) => setSelectedIntegration(e.target.value)}
              className="rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200"
            >
              <option value="">Select…</option>
              {integrations.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name} ({i.vendor})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-500">Device group (optional override)</label>
            <input
              value={deviceGroup}
              onChange={(e) => setDeviceGroup(e.target.value)}
              placeholder="uses integration's saved device group if blank"
              className="w-72 rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600"
            />
          </div>
          <button
            onClick={runAnalysis}
            disabled={!selectedIntegration || analyzing}
            className="rounded-lg bg-indigo-500 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {analyzing ? "Analyzing…" : "Analyze"}
          </button>
        </div>
        {integrations.length === 0 && (
          <p className="mt-3 text-xs text-zinc-500">
            No analyzable integrations yet — add a Panorama or PAN-OS credential under Integrations first.
          </p>
        )}
        {error && <p className="mt-3 text-xs text-red-400">{error}</p>}
      </div>

      {runs.length > 0 && (
        <div className="mb-6 rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
          <h2 className="mb-3 text-sm font-semibold text-zinc-200">Analysis history</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-zinc-500">
                  <th className="pb-2 pr-4 font-medium">When</th>
                  <th className="pb-2 pr-4 font-medium">Integration</th>
                  <th className="pb-2 pr-4 font-medium">Device group</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 pr-4 font-medium">Rules</th>
                  <th className="pb-2 font-medium">Findings</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="border-t border-white/[0.06]">
                    <td className="py-2 pr-4 text-zinc-400">{new Date(r.created_at).toLocaleString()}</td>
                    <td className="py-2 pr-4 text-zinc-300">{r.integration_name}</td>
                    <td className="py-2 pr-4 text-zinc-400">{r.device_group ?? "—"}</td>
                    <td className="py-2 pr-4">
                      {r.status === "ok" ? (
                        <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-400 ring-1 ring-inset ring-emerald-500/30">
                          ok
                        </span>
                      ) : (
                        <span
                          className="rounded-full bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-400 ring-1 ring-inset ring-red-500/30"
                          title={r.error_message}
                        >
                          error
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-4 text-zinc-400">{r.rule_count}</td>
                    <td className="py-2 text-zinc-400">
                      {r.status === "ok"
                        ? `${r.severity_counts.critical ?? 0} critical · ${r.severity_counts.warn ?? 0} warn · ${r.severity_counts.info ?? 0} info`
                        : r.error_message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-200">Rule review queue</h2>
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1 text-xs text-zinc-300"
          >
            <option value="">All severities</option>
            <option value="critical">Critical only</option>
            <option value="warn">Warn only</option>
            <option value="info">Info only</option>
          </select>
        </div>
        {rules.length === 0 ? (
          <p className="text-sm text-zinc-500">No rules analyzed yet. Run an analysis above.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-zinc-500">
                  <th className="pb-2 pr-4 font-medium">Rule</th>
                  <th className="pb-2 pr-4 font-medium">Action</th>
                  <th className="pb-2 pr-4 font-medium">Findings</th>
                  <th className="pb-2 pr-4 font-medium">Owner</th>
                  <th className="pb-2 pr-4 font-medium">Last reviewed</th>
                  <th className="pb-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id} className="border-t border-white/[0.06] align-top">
                    <td className="py-2 pr-4">
                      <div className="font-medium text-zinc-200">{r.rule_name}</div>
                      <div className="text-xs text-zinc-500">{r.integration_name}{r.device_group ? ` · ${r.device_group}` : ""}</div>
                      {r.removed_at && <div className="mt-0.5 text-xs text-amber-400">no longer on device as of last run</div>}
                    </td>
                    <td className="py-2 pr-4 text-zinc-400">{r.action}{r.disabled ? " (disabled)" : ""}</td>
                    <td className="py-2 pr-4">
                      <div className="flex flex-col gap-1">
                        {r.findings.length === 0 ? (
                          <span className="text-xs text-zinc-600">clean</span>
                        ) : (
                          r.findings.map((f, idx) => (
                            <div key={idx} className="flex items-center gap-1.5">
                              <SeverityBadge severity={f.severity} />
                              <span className="text-xs text-zinc-400" title={f.message}>
                                {CATEGORY_LABEL[f.category] ?? f.category}
                                {f.related_rule ? ` (${f.related_rule})` : ""}
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                    </td>
                    <td className="py-2 pr-4 text-zinc-400">{r.owner || "—"}</td>
                    <td className="py-2 pr-4 text-zinc-500">
                      {r.last_reviewed_at ? new Date(r.last_reviewed_at).toLocaleDateString() : "never"}
                    </td>
                    <td className="py-2">
                      <button
                        onClick={() => {
                          setReviewing(r);
                          setReviewForm({ owner: r.owner, review_note: r.review_note });
                        }}
                        className="rounded-lg border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-300 transition-colors hover:border-white/[0.16] hover:bg-white/[0.04]"
                      >
                        Review
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {reviewing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setReviewing(null)}>
          <div
            className="w-full max-w-md rounded-2xl border border-white/[0.08] bg-surface-2 p-5 shadow-elevated"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-1 text-sm font-semibold text-zinc-100">Review rule</h3>
            <p className="mb-4 text-xs text-zinc-500">{reviewing.rule_name}</p>
            <label className="mb-1 block text-xs font-medium text-zinc-500">Owner</label>
            <input
              value={reviewForm.owner}
              onChange={(e) => setReviewForm((f) => ({ ...f, owner: e.target.value }))}
              className="mb-3 w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200"
            />
            <label className="mb-1 block text-xs font-medium text-zinc-500">Note</label>
            <textarea
              value={reviewForm.review_note}
              onChange={(e) => setReviewForm((f) => ({ ...f, review_note: e.target.value }))}
              rows={3}
              className="mb-4 w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setReviewing(null)}
                className="rounded-lg border border-white/[0.08] px-3 py-1.5 text-sm text-zinc-300 hover:bg-white/[0.04]"
              >
                Cancel
              </button>
              <button
                onClick={submitReview}
                className="rounded-lg bg-indigo-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-400"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
