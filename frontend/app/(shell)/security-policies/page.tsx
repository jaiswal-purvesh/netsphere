"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";

// Phase 6 — Security Policies. Two halves:
//  1. RITM/connectivity-request sheet intake (.xlsx/.csv/.ods) — the format
//     the network team actually receives from ServiceNow (see
//     app/services/security_policy_intake.py's docstring for the exact
//     columns). Each resolvable row becomes an FwIntent, automatically
//     targeted at either the on-prem firewall or the cloud NSG/SG/SL that
//     protects the destination's own network (real CIDR-containment
//     lookup, app/services/security_policy_resolve.py) — never guessed.
//     Lifecycle actions (plan/PoA/approve/execute/rollback) on the created
//     intents happen on the Firewall Automation page, which now handles
//     every target_kind, not only Panorama.
//  2. A browser for the normalized SecurityGroup/SecurityRule objects
//     those intents deploy into — the Phase 6 upgrade of what used to be
//     Cloud Networks' free-text `security_groups` list.

type IntakeRowResult = {
  row_number: number;
  status: string;
  reason: string;
  intent_id: string | null;
  target_kind: string | null;
  target_label: string | null;
  source: string | null;
  destination: string | null;
  ports: string | null;
};

type SecurityPolicyBatch = {
  id: string;
  source_filename: string | null;
  source_format: string;
  row_count: number;
  resolved_count: number;
  unresolved_count: number;
  created_at: string;
};

type IntakeResponse = { batch: SecurityPolicyBatch; results: IntakeRowResult[] };

type SecurityRule = {
  id: string;
  direction: string;
  priority: number | null;
  action: string;
  protocol: string;
  port_low: number | null;
  port_high: number | null;
  cidr: string;
  status: string;
  source: string;
  managed_by_fwauto: boolean;
  ticket_ref: string | null;
  created_at: string;
};

type SecurityGroup = {
  id: string;
  network_id: string;
  network_name: string;
  cloud_account_id: string;
  provider: string;
  name: string;
  description: string;
  source: string;
  rule_count: number;
  created_at: string;
};

type SecurityGroupDetail = SecurityGroup & { rules: SecurityRule[] };

const PROVIDER_LABEL: Record<string, string> = {
  azure_nsg: "Azure NSG",
  aws_sg: "AWS Security Group",
  gcp_firewall: "GCP Firewall",
  oci_security_list: "OCI Security List",
  firewall: "Firewall",
};

function ProviderBadge({ provider }: { provider: string }) {
  const styles: Record<string, string> = {
    azure_nsg: "bg-blue-500/10 text-blue-400 ring-blue-500/30",
    aws_sg: "bg-amber-500/10 text-amber-400 ring-amber-500/30",
    gcp_firewall: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30",
    oci_security_list: "bg-red-500/10 text-red-400 ring-red-500/30",
    firewall: "bg-violet-500/10 text-violet-400 ring-violet-500/30",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${styles[provider] ?? "bg-white/[0.06] text-zinc-400 ring-white/[0.1]"}`}>
      {PROVIDER_LABEL[provider] ?? provider}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    created: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30",
    skipped_unresolved: "bg-amber-500/10 text-amber-400 ring-amber-500/30",
    error: "bg-red-500/10 text-red-400 ring-red-500/30",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${styles[status] ?? "bg-white/[0.06] text-zinc-400 ring-white/[0.1]"}`}>
      {status.replaceAll("_", " ")}
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

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.split(",", 2)[1] ?? "");
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export default function SecurityPoliciesPage() {
  const [tab, setTab] = useState<"intake" | "groups">("intake");

  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<IntakeResponse | null>(null);
  const [batches, setBatches] = useState<SecurityPolicyBatch[]>([]);

  const [groups, setGroups] = useState<SecurityGroup[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<SecurityGroupDetail | null>(null);

  async function loadBatches() {
    try {
      setBatches(await api.get<SecurityPolicyBatch[]>("/security-policy/batches"));
    } catch {
      /* non-fatal — the upload panel still works */
    }
  }

  async function loadGroups() {
    setGroupsLoading(true);
    try {
      setGroups(await api.get<SecurityGroup[]>("/security-policy/security-groups"));
    } finally {
      setGroupsLoading(false);
    }
  }

  useEffect(() => {
    loadBatches();
    loadGroups();
  }, []);

  async function handleFile(file: File) {
    setUploading(true);
    setUploadError(null);
    try {
      const content_base64 = await fileToBase64(file);
      const result = await api.post<IntakeResponse>("/security-policy/intake", {
        filename: file.name,
        content_base64,
      });
      setLastResult(result);
      await loadBatches();
      await loadGroups();
    } catch (e) {
      setUploadError(e instanceof ApiError ? String(e.message) : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function toggleGroup(id: string) {
    if (expanded === id) {
      setExpanded(null);
      setDetail(null);
      return;
    }
    setExpanded(id);
    setDetail(await api.get<SecurityGroupDetail>(`/security-policy/security-groups/${id}`));
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-zinc-50">Security Policies</h1>
      </div>
      <p className="mb-6 max-w-3xl text-sm text-zinc-500">
        Upload a RITM/connectivity-request sheet to create firewall and cloud NSG/SG/SL change
        requests automatically, or browse the normalized security groups those requests deploy
        into. Every created request still goes through the same guardrails → plan → Plan of Action
        → approval → execute pipeline as a hand-created request — manage that lifecycle from{" "}
        <Link href="/fw-automation" className="text-indigo-400 hover:underline">Firewall Automation</Link>.
      </p>

      <div className="mb-6 flex gap-2 border-b border-white/[0.08]">
        {(["intake", "groups"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === t ? "border-indigo-400 text-zinc-50" : "border-transparent text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {t === "intake" ? "RITM Intake" : "Security Groups"}
          </button>
        ))}
      </div>

      {tab === "intake" && (
        <div className="space-y-6">
          <div className="rounded-xl border border-dashed border-white/[0.12] bg-surface-2 p-6 text-center">
            <input
              type="file"
              accept=".xlsx,.csv,.ods"
              id="ritm-file"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFile(f);
                e.target.value = "";
              }}
            />
            <label htmlFor="ritm-file" className="btn-primary inline-block cursor-pointer">
              {uploading ? "Parsing…" : "Upload RITM sheet (.xlsx / .csv / .ods)"}
            </label>
            <p className="mt-2 text-xs text-zinc-500">
              Each row's destination is matched against known cloud networks (real CIDR
              containment) to pick Azure NSG / AWS SG / GCP firewall / OCI Security List, falling
              back to the on-prem firewall integration when the destination isn&rsquo;t in any
              known cloud network.
            </p>
            {uploadError && <p className="mt-3 text-sm text-red-400">{uploadError}</p>}
          </div>

          {lastResult && (
            <div>
              <div className="mb-3 grid grid-cols-3 gap-3 sm:grid-cols-3">
                <StatCard label="Rows in sheet" value={lastResult.batch.row_count} />
                <StatCard label="Requests created" value={lastResult.results.filter((r) => r.status === "created").length} />
                <StatCard label="Needs manual resolution" value={lastResult.batch.unresolved_count} />
              </div>
              <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface-2">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/[0.08] text-left text-xs uppercase tracking-wide text-zinc-500">
                      <th className="px-4 py-2 font-medium">Row</th>
                      <th className="px-4 py-2 font-medium">Source → Destination</th>
                      <th className="px-4 py-2 font-medium">Ports</th>
                      <th className="px-4 py-2 font-medium">Target</th>
                      <th className="px-4 py-2 font-medium">Status</th>
                      <th className="px-4 py-2 font-medium">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lastResult.results.map((r, idx) => (
                      <tr key={idx} className="border-b border-white/[0.04] last:border-0">
                        <td className="px-4 py-2 text-zinc-500">{r.row_number}</td>
                        <td className="px-4 py-2 font-mono text-xs text-zinc-400">
                          {r.source} → {r.destination}
                        </td>
                        <td className="px-4 py-2 font-mono text-xs text-zinc-500">{r.ports}</td>
                        <td className="px-4 py-2">
                          {r.target_kind ? (
                            <span className="flex items-center gap-1.5">
                              <ProviderBadge provider={r.target_kind} /> {r.target_label}
                            </span>
                          ) : (
                            <span className="text-zinc-600">—</span>
                          )}
                        </td>
                        <td className="px-4 py-2"><StatusBadge status={r.status} /></td>
                        <td className="px-4 py-2 text-xs text-zinc-500">
                          {r.intent_id ? (
                            <Link href="/fw-automation" className="text-indigo-400 hover:underline">manage in Firewall Automation</Link>
                          ) : (
                            r.reason
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div>
            <h2 className="mb-2 text-sm font-semibold text-zinc-300">Previous uploads</h2>
            {batches.length === 0 ? (
              <p className="text-sm text-zinc-500">No sheets uploaded yet.</p>
            ) : (
              <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface-2">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/[0.08] text-left text-xs uppercase tracking-wide text-zinc-500">
                      <th className="px-4 py-2 font-medium">File</th>
                      <th className="px-4 py-2 font-medium">Rows</th>
                      <th className="px-4 py-2 font-medium">Resolved</th>
                      <th className="px-4 py-2 font-medium">Unresolved</th>
                      <th className="px-4 py-2 font-medium">Uploaded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {batches.map((b) => (
                      <tr key={b.id} className="border-b border-white/[0.04] last:border-0">
                        <td className="px-4 py-2 font-mono text-zinc-300">{b.source_filename ?? "(untitled)"}</td>
                        <td className="px-4 py-2 text-zinc-500">{b.row_count}</td>
                        <td className="px-4 py-2 text-emerald-400">{b.resolved_count}</td>
                        <td className="px-4 py-2 text-amber-400">{b.unresolved_count}</td>
                        <td className="px-4 py-2 text-zinc-500">{new Date(b.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "groups" && (
        <div>
          {groupsLoading ? (
            <p className="text-sm text-zinc-500">Loading…</p>
          ) : groups.length === 0 ? (
            <p className="text-sm text-zinc-500">
              No security groups yet — one is created automatically the first time an intake row
              resolves to a cloud network without one.
            </p>
          ) : (
            <div className="space-y-2">
              {groups.map((g) => (
                <div key={g.id} className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface-2">
                  <button
                    onClick={() => toggleGroup(g.id)}
                    className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-white/[0.02]"
                  >
                    <span className="flex items-center gap-3">
                      <ProviderBadge provider={g.provider} />
                      <span className="font-medium text-zinc-100">{g.name}</span>
                      <span className="text-xs text-zinc-500">network: {g.network_name}</span>
                    </span>
                    <span className="text-xs text-zinc-500">{g.rule_count} rule{g.rule_count === 1 ? "" : "s"}</span>
                  </button>
                  {expanded === g.id && detail && (
                    <div className="border-t border-white/[0.08] px-4 py-3">
                      {detail.rules.length === 0 ? (
                        <p className="text-xs text-zinc-500">No rules yet.</p>
                      ) : (
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-left uppercase tracking-wide text-zinc-500">
                              <th className="py-1 pr-4 font-medium">Direction</th>
                              <th className="py-1 pr-4 font-medium">Action</th>
                              <th className="py-1 pr-4 font-medium">Protocol/Port</th>
                              <th className="py-1 pr-4 font-medium">CIDR</th>
                              <th className="py-1 pr-4 font-medium">Priority</th>
                              <th className="py-1 pr-4 font-medium">Source</th>
                              <th className="py-1 pr-4 font-medium">Ticket</th>
                            </tr>
                          </thead>
                          <tbody>
                            {detail.rules.map((r) => (
                              <tr key={r.id} className="border-t border-white/[0.04]">
                                <td className="py-1.5 pr-4 capitalize text-zinc-400">{r.direction}</td>
                                <td className={`py-1.5 pr-4 capitalize ${r.action === "allow" ? "text-emerald-400" : "text-red-400"}`}>{r.action}</td>
                                <td className="py-1.5 pr-4 font-mono text-zinc-400">
                                  {r.protocol}/{r.port_low === r.port_high ? r.port_low : `${r.port_low}-${r.port_high}`}
                                </td>
                                <td className="py-1.5 pr-4 font-mono text-zinc-400">{r.cidr}</td>
                                <td className="py-1.5 pr-4 text-zinc-500">{r.priority ?? "—"}</td>
                                <td className="py-1.5 pr-4 text-zinc-500">
                                  {r.source}{r.managed_by_fwauto ? " (fwauto)" : ""}
                                </td>
                                <td className="py-1.5 pr-4 text-zinc-500">{r.ticket_ref ?? "—"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
