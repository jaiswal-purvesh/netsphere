"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

// Firewall rule execution automation — Phase 3 of
// claude/firewall-policy-automation-design.md's phasing table (Panorama/
// PAN-OS only; FortiManager joins in Phase 4). Walks a request through the
// same gates the design doc specifies: intent -> plan (guardrails +
// redundancy analysis) -> generated Plan of Action -> human approval
// (separation of duties enforced server-side) -> execute -> verify, with
// automatic rollback on a failed deny push and a manual rollback for a
// verified change the team decides to back out.

type Vendor = "panorama" | "pan_os";

type Integration = {
  id: string;
  vendor: string;
  name: string;
  device_group: string | null;
  is_active: boolean;
};

type Finding = { rule: string; severity: "hard" | "warn"; message: string };

type Intent = {
  id: string;
  ticket_ref: string;
  justification: string;
  action: "allow" | "deny";
  logging: string;
  expires_at: string | null;
  source: { cidr: string }[];
  destination: { cidr: string }[];
  service: { proto: string; port_low: number | null; port_high: number | null }[];
  target_kind?: string;
  integration_id: string | null;
  device_group: string | null;
  security_group_id?: string | null;
  target_label?: string | null;
  batch_id?: string | null;
  status: string;
  risk_score: number;
  guardrail_findings: Finding[];
  analysis: { verdict?: string; covering_rule?: string | null; blocking_rule?: string | null; notes?: string[] };
  created_at: string;
  updated_at: string;
};

type Plan = {
  id: string;
  intent_id: string;
  plan_hash: string;
  risk_score: number;
  guardrail_findings: Finding[];
  analysis: Intent["analysis"];
  artifact: Record<string, unknown>;
  human_diff_text: string;
  device_config_version: string | null;
};

type Poa = {
  id: string;
  plan_id: string;
  poa_revision: string;
  rendered_markdown: string;
  signed_off_by_id: string | null;
  signed_off_at: string | null;
};

type Execution = {
  id: string;
  state: string;
  snapshot_ref: string | null;
  commit_job_id: string | null;
  push_job_id: string | null;
  verify_result: Record<string, unknown>;
  error_message: string;
  rolled_back: boolean;
  started_at: string | null;
  finished_at: string | null;
};

const STATUS_STYLE: Record<string, string> = {
  received: "bg-white/[0.06] text-zinc-400 ring-1 ring-inset ring-white/[0.1]",
  awaiting_approval: "bg-amber-500/10 text-amber-400 ring-1 ring-inset ring-amber-500/30",
  approved: "bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/30",
  executing: "bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/30",
  applied_verified: "bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/30",
  no_change_required: "bg-white/[0.06] text-zinc-500 ring-1 ring-inset ring-white/[0.1]",
  rejected: "bg-red-500/10 text-red-400 ring-1 ring-inset ring-red-500/30",
  failed: "bg-red-500/10 text-red-400 ring-1 ring-inset ring-red-500/30",
  needs_human: "bg-red-500/10 text-red-400 ring-1 ring-inset ring-red-500/30",
  partial: "bg-amber-500/10 text-amber-400 ring-1 ring-inset ring-amber-500/30",
  rolled_back: "bg-white/[0.1] text-zinc-400 ring-1 ring-inset ring-white/[0.1]",
};

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status] ?? "bg-white/[0.06] text-zinc-500"}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}

const emptyForm = {
  ticket_ref: "",
  justification: "",
  action: "allow" as "allow" | "deny",
  logging: "session_end",
  expires_at: "",
  source_cidr: "",
  destination_cidr: "",
  proto: "tcp",
  port_low: "",
  port_high: "",
  integration_id: "",
  device_group: "",
};

export default function FwAutomationPage() {
  const [intents, setIntents] = useState<Intent[]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [creating, setCreating] = useState(false);

  const [selected, setSelected] = useState<Intent | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [poa, setPoa] = useState<Poa | null>(null);
  const [execution, setExecution] = useState<Execution | null>(null);
  const [busy, setBusy] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [intentRows, integrationRows] = await Promise.all([
        api.get<Intent[]>("/fw-intents"),
        api.get<Integration[]>("/integrations"),
      ]);
      setIntents(intentRows);
      // Only panorama/pan_os are supported for execution in this phase —
      // NGFW entries have no credentials of their own, and FortiGate lands
      // in Phase 4.
      const flat: Integration[] = [];
      for (const i of integrationRows as unknown as (Integration & { children?: Integration[] })[]) {
        if (i.vendor === "panorama" || i.vendor === "pan_os") flat.push(i);
      }
      setIntegrations(flat);
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function openDetail(intent: Intent) {
    setSelected(intent);
    setPlan(null);
    setPoa(null);
    setExecution(null);
    setDetailError(null);
    await refreshDetail(intent.id);
  }

  async function refreshDetail(intentId: string) {
    try {
      const fresh = await api.get<Intent>(`/fw-intents/${intentId}`);
      setSelected(fresh);
    } catch {
      /* keep previous */
    }
    try {
      const p = await api.get<Plan>(`/fw-intents/${intentId}/plan`);
      setPlan(p);
      try {
        setPoa(await api.get<Poa>(`/fw-intents/${intentId}/poa`));
      } catch {
        setPoa(null);
      }
    } catch {
      setPlan(null);
      setPoa(null);
    }
    try {
      setExecution(await api.get<Execution>(`/fw-intents/${intentId}/execution`));
    } catch {
      setExecution(null);
    }
  }

  async function onCreate() {
    setCreating(true);
    setError(null);
    try {
      const payload = {
        ticket_ref: form.ticket_ref,
        justification: form.justification,
        action: form.action,
        logging: form.logging,
        expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
        source: [{ cidr: form.source_cidr }],
        destination: [{ cidr: form.destination_cidr }],
        service: [{ proto: form.proto, port_low: form.port_low ? Number(form.port_low) : null, port_high: form.port_high ? Number(form.port_high) : Number(form.port_low) || null }],
        integration_id: form.integration_id,
        device_group: form.device_group || null,
      };
      const created = await api.post<Intent>("/fw-intents", payload);
      setShowCreate(false);
      setForm(emptyForm);
      await load();
      await openDetail(created);
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "create failed");
    } finally {
      setCreating(false);
    }
  }

  async function onPlan() {
    if (!selected) return;
    setBusy(true);
    setDetailError(null);
    try {
      await refreshDetail(selected.id);
      await api.post(`/fw-intents/${selected.id}/plan`);
      await refreshDetail(selected.id);
      await load();
    } catch (e) {
      setDetailError(e instanceof ApiError ? String(e.detail) : "plan failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSignoff() {
    if (!selected) return;
    setBusy(true);
    setDetailError(null);
    try {
      await api.post(`/fw-intents/${selected.id}/poa/signoff`);
      await refreshDetail(selected.id);
    } catch (e) {
      setDetailError(e instanceof ApiError ? String(e.detail) : "signoff failed");
    } finally {
      setBusy(false);
    }
  }

  async function onApprove() {
    if (!selected || !plan || !poa) return;
    setBusy(true);
    setDetailError(null);
    try {
      await api.post(`/fw-intents/${selected.id}/approve`, { plan_hash: plan.plan_hash, poa_revision: poa.poa_revision, comment: "" });
      await refreshDetail(selected.id);
      await load();
    } catch (e) {
      setDetailError(e instanceof ApiError ? String(e.detail) : "approve failed");
    } finally {
      setBusy(false);
    }
  }

  async function onReject() {
    if (!selected) return;
    const reason = window.prompt("Reason for rejecting?") || "";
    setBusy(true);
    setDetailError(null);
    try {
      await api.post(`/fw-intents/${selected.id}/reject`, { reason });
      await refreshDetail(selected.id);
      await load();
    } catch (e) {
      setDetailError(e instanceof ApiError ? String(e.detail) : "reject failed");
    } finally {
      setBusy(false);
    }
  }

  async function onExecute() {
    if (!selected) return;
    setBusy(true);
    setDetailError(null);
    try {
      await api.post(`/fw-intents/${selected.id}/execute`);
      await refreshDetail(selected.id);
      await load();
    } catch (e) {
      setDetailError(e instanceof ApiError ? String(e.detail) : "execute failed");
    } finally {
      setBusy(false);
    }
  }

  async function onRollback() {
    if (!selected) return;
    if (!window.confirm("Roll back this verified change? This reverts the Panorama config to the pre-change snapshot.")) return;
    setBusy(true);
    setDetailError(null);
    try {
      await api.post(`/fw-intents/${selected.id}/rollback`);
      await refreshDetail(selected.id);
      await load();
    } catch (e) {
      setDetailError(e instanceof ApiError ? String(e.detail) : "rollback failed");
    } finally {
      setBusy(false);
    }
  }

  const hardFailures = (plan?.guardrail_findings ?? []).some((f) => f.severity === "hard");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-zinc-50">Firewall Automation</h2>
          <p className="text-sm text-zinc-500">
            Request → plan (guardrails + redundancy) → Plan of Action → approve → execute → verify, against Panorama
            and standalone PAN-OS. Uses the credentials saved on the Integrations page. FortiManager execution is a
            later phase.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-xl bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
        >
          New request
        </button>
      </div>

      {error && <p className="rounded-xl border border-red-900 bg-red-500/10 px-3 py-2 text-sm text-red-400">{error}</p>}
      {loading && <p className="text-sm text-zinc-500">Loading…</p>}

      {!loading && (
        <div className="rounded-xl border border-white/[0.08] bg-surface-2">
          {intents.length === 0 ? (
            <p className="px-4 py-6 text-sm text-zinc-500">No requests yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.08] text-left text-xs uppercase text-zinc-500">
                  <th className="px-4 py-2 font-medium">Ticket</th>
                  <th className="px-4 py-2 font-medium">Action</th>
                  <th className="px-4 py-2 font-medium">Source → Destination</th>
                  <th className="px-4 py-2 font-medium">Target</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Risk</th>
                  <th className="px-4 py-2 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {intents.map((i) => (
                  <tr key={i.id} className="cursor-pointer hover:bg-white/[0.04]" onClick={() => openDetail(i)}>
                    <td className="px-4 py-2 font-mono font-medium text-zinc-100">{i.ticket_ref}</td>
                    <td className="px-4 py-2 capitalize">{i.action}</td>
                    <td className="px-4 py-2 font-mono text-zinc-500">
                      {i.source.map((s) => s.cidr).join(", ")} → {i.destination.map((d) => d.cidr).join(", ")}
                    </td>
                    <td className="px-4 py-2 text-xs text-zinc-400">
                      <span className="rounded-full bg-white/[0.06] px-2 py-0.5 ring-1 ring-inset ring-white/[0.1]">
                        {(i.target_kind ?? "firewall").replaceAll("_", " ")}
                      </span>
                      {i.target_label ? <span className="ml-1.5 text-zinc-500">{i.target_label}</span> : null}
                    </td>
                    <td className="px-4 py-2"><StatusPill status={i.status} /></td>
                    <td className="px-4 py-2">{i.risk_score}</td>
                    <td className="px-4 py-2 text-zinc-500">{new Date(i.updated_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl bg-surface-2 p-5 shadow-xl">
            <h3 className="mb-3 text-sm font-semibold text-zinc-100">New connectivity request</h3>
            <div className="space-y-3">
              <Field label="Ticket ref">
                <input className="input" value={form.ticket_ref} onChange={(e) => setForm({ ...form, ticket_ref: e.target.value })} placeholder="CHG0041882" />
              </Field>
              <Field label="Justification">
                <input className="input" value={form.justification} onChange={(e) => setForm({ ...form, justification: e.target.value })} />
              </Field>
              <Field label="Firewall integration">
                <select className="input" value={form.integration_id} onChange={(e) => setForm({ ...form, integration_id: e.target.value })}>
                  <option value="">Select…</option>
                  {integrations.map((i) => (
                    <option key={i.id} value={i.id}>{i.name} ({i.vendor})</option>
                  ))}
                </select>
              </Field>
              <Field label="Device group (Panorama only — leave blank for standalone PAN-OS)">
                <input className="input" value={form.device_group} onChange={(e) => setForm({ ...form, device_group: e.target.value })} placeholder="DG-Prod" />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Action">
                  <select className="input" value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value as "allow" | "deny" })}>
                    <option value="allow">allow</option>
                    <option value="deny">deny</option>
                  </select>
                </Field>
                <Field label="Logging">
                  <select className="input" value={form.logging} onChange={(e) => setForm({ ...form, logging: e.target.value })}>
                    <option value="session_end">session_end</option>
                    <option value="session_start">session_start</option>
                    <option value="both">both</option>
                    <option value="none">none</option>
                  </select>
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Source CIDR"><input className="input" value={form.source_cidr} onChange={(e) => setForm({ ...form, source_cidr: e.target.value })} placeholder="10.42.16.0/24" /></Field>
                <Field label="Destination CIDR"><input className="input" value={form.destination_cidr} onChange={(e) => setForm({ ...form, destination_cidr: e.target.value })} placeholder="10.42.64.0/26" /></Field>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Protocol">
                  <select className="input" value={form.proto} onChange={(e) => setForm({ ...form, proto: e.target.value })}>
                    <option value="tcp">tcp</option>
                    <option value="udp">udp</option>
                  </select>
                </Field>
                <Field label="Port low"><input className="input" value={form.port_low} onChange={(e) => setForm({ ...form, port_low: e.target.value })} placeholder="5432" /></Field>
                <Field label="Port high (optional)"><input className="input" value={form.port_high} onChange={(e) => setForm({ ...form, port_high: e.target.value })} /></Field>
              </div>
              <Field label="Expires (optional — permanent rules get flagged for extra review)">
                <input type="date" className="input" value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })} />
              </Field>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button className="rounded-xl px-3 py-1.5 text-sm text-zinc-500 hover:bg-white/[0.06]" onClick={() => setShowCreate(false)}>Cancel</button>
              <button
                disabled={creating || !form.ticket_ref || !form.integration_id || !form.source_cidr || !form.destination_cidr || !form.port_low}
                className="rounded-xl bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                onClick={onCreate}
              >
                {creating ? "Creating…" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-surface-2 p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-zinc-100">{selected.ticket_ref}</h3>
                <p className="text-xs text-zinc-500">{selected.justification}</p>
              </div>
              <div className="flex items-center gap-2">
                <StatusPill status={selected.status} />
                <button className="text-zinc-500 hover:text-zinc-500" onClick={() => setSelected(null)}>✕</button>
              </div>
            </div>

            {detailError && <p className="mb-3 rounded-xl border border-red-900 bg-red-500/10 px-3 py-2 text-sm text-red-400">{detailError}</p>}

            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3 text-xs text-zinc-500">
                <div>Action: <span className="font-medium text-zinc-600">{selected.action}</span></div>
                <div>Risk score: <span className="font-medium text-zinc-600">{selected.risk_score}</span></div>
                <div>Source: {selected.source.map((s) => s.cidr).join(", ")}</div>
                <div>Destination: {selected.destination.map((d) => d.cidr).join(", ")}</div>
              </div>

              <div className="flex flex-wrap gap-2">
                <button disabled={busy || ["executing", "applied_verified"].includes(selected.status)} onClick={onPlan} className="btn">Plan / re-plan</button>
                {poa && !poa.signed_off_at && <button disabled={busy} onClick={onSignoff} className="btn">Sign off PoA</button>}
                {selected.status === "awaiting_approval" && plan && poa && (
                  <>
                    <button disabled={busy} onClick={onApprove} className="btn-primary">Approve</button>
                    <button disabled={busy} onClick={onReject} className="btn-danger">Reject</button>
                  </>
                )}
                {selected.status === "approved" && <button disabled={busy} onClick={onExecute} className="btn-primary">Execute</button>}
                {selected.status === "applied_verified" && <button disabled={busy} onClick={onRollback} className="btn-danger">Roll back</button>}
              </div>

              {plan && (
                <div className="rounded-xl border border-white/[0.08] p-3">
                  <p className="mb-1 text-xs font-semibold uppercase text-zinc-500">Plan — {plan.plan_hash.slice(0, 16)}…</p>
                  {plan.guardrail_findings.length > 0 && (
                    <ul className="mb-2 space-y-1">
                      {plan.guardrail_findings.map((f, idx) => (
                        <li key={idx} className={`text-xs ${f.severity === "hard" ? "text-red-400" : "text-amber-400"}`}>
                          [{f.severity}] {f.rule}: {f.message}
                        </li>
                      ))}
                    </ul>
                  )}
                  {plan.analysis?.verdict && (
                    <p className="mb-2 text-xs text-zinc-500">
                      Analysis: <span className="font-medium">{plan.analysis.verdict}</span>
                      {plan.analysis.covering_rule ? ` (${plan.analysis.covering_rule})` : ""}
                      {plan.analysis.blocking_rule ? ` (blocked by ${plan.analysis.blocking_rule})` : ""}
                    </p>
                  )}
                  <pre className="max-h-40 overflow-auto rounded bg-white/[0.04] p-2 text-xs text-zinc-500">{plan.human_diff_text || "(no change required)"}</pre>
                  {hardFailures && <p className="mt-2 text-xs font-medium text-red-400">Hard guardrail failures — this plan cannot be approved.</p>}
                </div>
              )}

              {poa && (
                <div className="rounded-xl border border-white/[0.08] p-3">
                  <div className="mb-1 flex items-center justify-between">
                    <p className="text-xs font-semibold uppercase text-zinc-500">Plan of Action</p>
                    {poa.signed_off_at ? (
                      <span className="text-xs text-emerald-400">Signed off {new Date(poa.signed_off_at).toLocaleString()}</span>
                    ) : (
                      <span className="text-xs text-amber-400">Awaiting sign-off</span>
                    )}
                  </div>
                  <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-white/[0.04] p-2 text-xs text-zinc-500">{poa.rendered_markdown}</pre>
                </div>
              )}

              {execution && (
                <div className="rounded-xl border border-white/[0.08] p-3">
                  <p className="mb-1 text-xs font-semibold uppercase text-zinc-500">Execution — {execution.state}</p>
                  {execution.error_message && <p className="text-xs text-red-400">{execution.error_message}</p>}
                  <div className="grid grid-cols-2 gap-2 text-xs text-zinc-500">
                    <div>Snapshot: {execution.snapshot_ref || "—"}</div>
                    <div>Commit job: {execution.commit_job_id || "—"}</div>
                    <div>Push job: {execution.push_job_id || "—"}</div>
                    <div>Rolled back: {execution.rolled_back ? "yes" : "no"}</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <style jsx global>{`
        .input { display: block; width: 100%; background: #0b1220; border: 1px solid #1e293b; border-radius: 0.375rem; padding: 0.375rem 0.5rem; font-size: 0.875rem; color: #e2e8f0; }
        .input:focus { outline: none; border-color: #0891b2; }
        .btn { border: 1px solid #1e293b; border-radius: 0.375rem; padding: 0.375rem 0.75rem; font-size: 0.8rem; color: #94a3b8; }
        .btn:hover { background: #1e293b; }
        .btn-primary { background: #0891b2; color: white; border-radius: 0.375rem; padding: 0.375rem 0.75rem; font-size: 0.8rem; font-weight: 500; }
        .btn-primary:hover { background: #06b6d4; }
        .btn-danger { background: rgba(239,68,68,0.1); color: #f87171; border: 1px solid rgba(239,68,68,0.3); border-radius: 0.375rem; padding: 0.375rem 0.75rem; font-size: 0.8rem; font-weight: 500; }
        .btn-danger:hover { background: rgba(239,68,68,0.18); }
      `}</style>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-zinc-500">{label}</span>
      {children}
    </label>
  );
}
