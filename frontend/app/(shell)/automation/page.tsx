"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type ReferenceFileEntry = {
  kind: string;
  label: string;
  uploaded: boolean;
  filename: string | null;
  size_bytes: number | null;
  updated_at: string | null;
};

type PoaRunSummary = {
  id: string;
  ritm_number: string;
  input_filename: string;
  row_count: number;
  manual_count: number;
  invalid_count: number;
  warnings: string[];
  created_at: string;
};

type PoaRunDetail = PoaRunSummary & {
  rows: Record<string, string>[];
  metadata_json: Record<string, unknown>;
};

type AutomationChange = {
  id: string;
  kind: "poa_run" | "fw_intent";
  title: string;
  status: string;
  status_bucket: "in_progress" | "completed" | "rejected" | "rolled_back";
  ticket_ref: string | null;
  requested_by: string | null;
  target_label: string | null;
  created_at: string;
  detail: Record<string, unknown>;
};

type AutomationChangesSummary = {
  poa_run_count: number;
  fw_intent_count: number;
  fw_intent_in_progress: number;
  fw_intent_completed: number;
  fw_intent_rejected: number;
  fw_intent_rolled_back: number;
  fw_intent_firewall_targets: number;
  fw_intent_cloud_targets: number;
};

type AutomationAuditEntry = {
  id: string;
  user_label: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  result: string;
  after: Record<string, unknown> | null;
  created_at: string;
};

function formatBytes(n: number | null): string {
  if (n === null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-zinc-50">{value}</p>
    </div>
  );
}

const BUCKET_STYLE: Record<AutomationChange["status_bucket"], string> = {
  in_progress: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  completed: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  rejected: "bg-red-500/10 text-red-400 border-red-500/20",
  rolled_back: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
};

function StatusBadge({ change }: { change: AutomationChange }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${BUCKET_STYLE[change.status_bucket]}`}>
      {change.status.replace(/_/g, " ")}
    </span>
  );
}

function KindBadge({ kind }: { kind: AutomationChange["kind"] }) {
  return kind === "poa_run" ? (
    <span className="rounded-full border border-indigo-500/20 bg-indigo-500/10 px-2 py-0.5 text-xs font-medium text-indigo-400">
      POA document
    </span>
  ) : (
    <span className="rounded-full border border-sky-500/20 bg-sky-500/10 px-2 py-0.5 text-xs font-medium text-sky-400">
      Policy change (fwauto)
    </span>
  );
}

function ChangesHubTab() {
  const [changes, setChanges] = useState<AutomationChange[]>([]);
  const [summary, setSummary] = useState<AutomationChangesSummary | null>(null);
  const [audit, setAudit] = useState<AutomationAuditEntry[]>([]);
  const [showAudit, setShowAudit] = useState(false);
  const [filter, setFilter] = useState<"all" | "poa_run" | "fw_intent">("all");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [c, s] = await Promise.all([
        api.get<AutomationChange[]>("/automation/changes?limit=200"),
        api.get<AutomationChangesSummary>("/automation/changes/summary"),
      ]);
      setChanges(c);
      setSummary(s);
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "could not load the automation hub feed");
    }
  }

  async function loadAudit() {
    try {
      setAudit(await api.get<AutomationAuditEntry[]>("/automation/audit?limit=200"));
      setShowAudit(true);
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "could not load the audit trail");
    }
  }

  useEffect(() => {
    load();
  }, []);

  const filtered = changes.filter((c) => filter === "all" || c.kind === filter);

  return (
    <div>
      <p className="mb-4 text-sm text-zinc-500">
        Every automation activity in one place — POA documents from this module, and firewall / cloud NSG-SG-SL
        policy changes from fwauto&apos;s intent → plan → approval → execute pipeline (Phase 6). This is the
        converged view ARCHITECTURE.md §1 describes: fwauto stays the execution engine, this hub is its shared
        UI/RBAC/audit layer.
      </p>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {summary && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="POA documents" value={summary.poa_run_count} />
          <StatCard label="Policy changes (fwauto)" value={summary.fw_intent_count} />
          <StatCard label="In progress" value={summary.fw_intent_in_progress} />
          <StatCard label="Rejected / rolled back" value={summary.fw_intent_rejected + summary.fw_intent_rolled_back} />
        </div>
      )}
      {summary && (
        <p className="mb-6 text-xs text-zinc-500">
          Of the {summary.fw_intent_count} policy changes: {summary.fw_intent_firewall_targets} targeted an on-prem
          firewall, {summary.fw_intent_cloud_targets} targeted a cloud NSG/SG/Security List.
        </p>
      )}

      <div className="mb-4 flex items-center justify-between">
        <div className="flex gap-2">
          {(["all", "fw_intent", "poa_run"] as const).map((k) => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className={`rounded-xl border px-3 py-1.5 text-xs font-medium ${
                filter === k
                  ? "border-indigo-500/40 bg-indigo-500/10 text-indigo-400"
                  : "border-white/[0.08] text-zinc-500"
              }`}
            >
              {k === "all" ? "All changes" : k === "fw_intent" ? "Policy changes" : "POA documents"}
            </button>
          ))}
        </div>
        <button onClick={loadAudit} className="text-xs font-medium text-indigo-400">
          View audit trail →
        </button>
      </div>

      <div className="rounded-xl border border-white/[0.08] bg-surface-2">
        <ul className="divide-y divide-white/[0.06]">
          {filtered.length === 0 && <li className="px-4 py-6 text-center text-sm text-zinc-500">Nothing here yet</li>}
          {filtered.map((c) => (
            <li key={`${c.kind}-${c.id}`} className="px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <KindBadge kind={c.kind} />
                    <StatusBadge change={c} />
                  </div>
                  <p className="mt-1 truncate text-sm font-medium text-zinc-100">{c.title}</p>
                  <p className="mt-0.5 text-xs text-zinc-500">
                    {c.requested_by ?? "unknown requester"}
                    {c.target_label && <> · {c.target_label}</>}
                  </p>
                </div>
                <span className="shrink-0 text-xs text-zinc-500">{new Date(c.created_at).toLocaleString()}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>

      {showAudit && (
        <div className="mt-6 rounded-xl border border-white/[0.08] bg-surface-2">
          <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-3">
            <span className="text-sm font-medium text-zinc-600">Audit trail — firewall &amp; POA actions</span>
            <button onClick={() => setShowAudit(false)} className="text-xs font-medium text-zinc-500">
              Hide
            </button>
          </div>
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/[0.08] text-left text-zinc-500">
                  <th className="px-3 py-2 font-medium">When</th>
                  <th className="px-3 py-2 font-medium">Who</th>
                  <th className="px-3 py-2 font-medium">Action</th>
                  <th className="px-3 py-2 font-medium">Resource</th>
                  <th className="px-3 py-2 font-medium">Result</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id} className="border-b border-white/[0.05]">
                    <td className="px-3 py-1.5 whitespace-nowrap">{new Date(a.created_at).toLocaleString()}</td>
                    <td className="px-3 py-1.5">{a.user_label ?? "—"}</td>
                    <td className="px-3 py-1.5">{a.action}</td>
                    <td className="px-3 py-1.5">
                      {a.resource_type}/{a.resource_id?.slice(0, 8)}
                    </td>
                    <td className="px-3 py-1.5">
                      <span className={a.result === "success" ? "text-emerald-400" : "text-red-400"}>{a.result}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function PoaGeneratorTab() {
  const [referenceFiles, setReferenceFiles] = useState<ReferenceFileEntry[]>([]);
  const [uploadingKind, setUploadingKind] = useState<string | null>(null);
  const [refError, setRefError] = useState<string | null>(null);

  const [ritmNumber, setRitmNumber] = useState("");
  const [description, setDescription] = useState("");
  const [changeOwner, setChangeOwner] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const [runs, setRuns] = useState<PoaRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<PoaRunDetail | null>(null);

  async function loadReferenceFiles() {
    try {
      setReferenceFiles(await api.get<ReferenceFileEntry[]>("/automation/poa/reference-files"));
    } catch (e) {
      setRefError(e instanceof ApiError ? String(e.detail) : "could not load reference files");
    }
  }

  async function loadRuns() {
    try {
      setRuns(await api.get<PoaRunSummary[]>("/automation/poa/runs"));
    } catch {
      /* run history is a convenience list — a load failure here doesn't block the rest of the page */
    }
  }

  useEffect(() => {
    loadReferenceFiles();
    loadRuns();
  }, []);

  async function doUploadReferenceFile(kind: string, e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploadingKind(kind);
    setRefError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      await api.putForm(`/automation/poa/reference-files/${kind}`, form);
      await loadReferenceFiles();
    } catch (e) {
      setRefError(e instanceof ApiError ? JSON.stringify(e.detail) : "upload failed");
    } finally {
      setUploadingKind(null);
    }
  }

  async function doRemoveReferenceFile(kind: string) {
    setUploadingKind(kind);
    setRefError(null);
    try {
      await api.delete(`/automation/poa/reference-files/${kind}`);
      await loadReferenceFiles();
    } catch (e) {
      setRefError(e instanceof ApiError ? JSON.stringify(e.detail) : "remove failed");
    } finally {
      setUploadingKind(null);
    }
  }

  async function doCreateRun(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const fileInput = form.elements.namedItem("input_file") as HTMLInputElement;
    const file = fileInput.files?.[0];
    if (!file) {
      setRunError("Choose a RITM input file (CSV, Excel, ODS, or ODT).");
      return;
    }
    setRunning(true);
    setRunError(null);
    try {
      const body = new FormData();
      body.append("input_file", file);
      if (ritmNumber) body.append("ritm_number", ritmNumber);
      body.append(
        "metadata",
        JSON.stringify({
          description_of_change: description,
          change_owner: changeOwner,
        }),
      );
      const run = await api.postForm<PoaRunDetail>("/automation/poa/runs", body);
      setSelectedRun(run);
      fileInput.value = "";
      await loadRuns();
    } catch (e) {
      setRunError(e instanceof ApiError ? JSON.stringify(e.detail) : "POA generation failed");
    } finally {
      setRunning(false);
    }
  }

  async function openRun(id: string) {
    try {
      setSelectedRun(await api.get<PoaRunDetail>(`/automation/poa/runs/${id}`));
    } catch (e) {
      setRunError(e instanceof ApiError ? String(e.detail) : "could not load run");
    }
  }

  async function downloadExcel(id: string, ritm: string) {
    await api.downloadFile(`/automation/poa/runs/${id}/excel`, `${ritm}-POA.xlsx`);
  }

  async function downloadDocx(id: string, ritm: string) {
    await api.downloadFile(`/automation/poa/runs/${id}/docx`, `${ritm}-POA.docx`);
  }

  const uploadedCount = referenceFiles.filter((r) => r.uploaded).length;

  return (
    <div>
      <p className="mb-6 text-sm text-zinc-500">
        Generate a Plan of Action (POA) — an enriched Excel + a branded Word document — from a RITM network-change
        request, using the reference inventories below.
      </p>

      <div className="mb-6 rounded-xl border border-white/[0.08] bg-surface-2">
        <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-3">
          <span className="text-sm font-medium text-zinc-600">Reference inventories</span>
          <span className="text-xs text-zinc-500">{uploadedCount} / {referenceFiles.length} uploaded</span>
        </div>
        {refError && <p className="px-4 pt-3 text-sm text-red-400">{refError}</p>}
        <ul className="divide-y divide-white/[0.06]">
          {referenceFiles.map((r) => (
            <li key={r.kind} className="flex items-center justify-between px-4 py-3">
              <div>
                <p className="text-sm font-medium text-zinc-100">{r.label}</p>
                <p className="text-xs text-zinc-500">
                  {r.uploaded ? (
                    <>
                      {r.filename} · {formatBytes(r.size_bytes)} · updated {r.updated_at ? new Date(r.updated_at).toLocaleString() : ""}
                    </>
                  ) : (
                    "Not uploaded — rows depending on this sheet will need manual entry"
                  )}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <label className="cursor-pointer rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500">
                  {uploadingKind === r.kind ? "Working…" : r.uploaded ? "Replace" : "Upload"}
                  <input
                    type="file"
                    accept=".csv,.xlsx,.xls,.ods"
                    onChange={(e) => doUploadReferenceFile(r.kind, e)}
                    disabled={uploadingKind === r.kind}
                    className="hidden"
                  />
                </label>
                {r.uploaded && (
                  <button
                    onClick={() => doRemoveReferenceFile(r.kind)}
                    disabled={uploadingKind === r.kind}
                    className="rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500 disabled:opacity-40"
                  >
                    Remove
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4">
          <p className="mb-3 text-sm font-medium text-zinc-600">New POA run</p>
          <form onSubmit={doCreateRun} className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-zinc-500">RITM input file</label>
              <input
                type="file"
                name="input_file"
                accept=".csv,.xlsx,.xls,.ods,.odt"
                className="block w-full text-sm text-zinc-500"
              />
              <p className="mt-1 text-xs text-zinc-500">CSV, Excel, ODS, or ODT — columns: Source IP, Destination IP, Destination Port, …</p>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-zinc-500">RITM number (optional — parsed from the filename otherwise)</label>
              <input
                className="w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                placeholder="RITM1234567"
                value={ritmNumber}
                onChange={(e) => setRitmNumber(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-zinc-500">Description of change</label>
              <input
                className="w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-zinc-500">Change owner</label>
              <input
                className="w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                value={changeOwner}
                onChange={(e) => setChangeOwner(e.target.value)}
              />
            </div>
            <button
              type="submit"
              disabled={running}
              className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
            >
              {running ? "Generating…" : "Generate POA"}
            </button>
            {runError && <p className="text-sm text-red-400">{runError}</p>}
          </form>
        </div>

        <div className="rounded-xl border border-white/[0.08] bg-surface-2">
          <div className="border-b border-white/[0.08] px-4 py-3">
            <span className="text-sm font-medium text-zinc-600">Run history</span>
          </div>
          <ul className="max-h-96 divide-y divide-white/[0.06] overflow-y-auto">
            {runs.length === 0 && <li className="px-4 py-6 text-center text-sm text-zinc-500">No runs yet</li>}
            {runs.map((r) => (
              <li key={r.id} className="px-4 py-3">
                <button onClick={() => openRun(r.id)} className="w-full text-left">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-zinc-100">{r.ritm_number}</span>
                    <span className="text-xs text-zinc-500">{new Date(r.created_at).toLocaleString()}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-zinc-500">
                    {r.row_count} row{r.row_count === 1 ? "" : "s"}
                    {r.manual_count > 0 && <span className="text-amber-400"> · {r.manual_count} manual</span>}
                    {r.invalid_count > 0 && <span className="text-red-400"> · {r.invalid_count} invalid</span>}
                  </p>
                </button>
                <div className="mt-1.5 flex gap-2">
                  <button onClick={() => downloadExcel(r.id, r.ritm_number)} className="text-xs font-medium text-indigo-400">
                    Excel
                  </button>
                  <button onClick={() => downloadDocx(r.id, r.ritm_number)} className="text-xs font-medium text-indigo-400">
                    Word
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {selectedRun && (
        <div className="mt-6 rounded-xl border border-white/[0.08] bg-surface-2">
          <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-3">
            <span className="text-sm font-medium text-zinc-600">{selectedRun.ritm_number} — enriched rows</span>
            <div className="flex gap-2">
              <button
                onClick={() => downloadExcel(selectedRun.id, selectedRun.ritm_number)}
                className="rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500"
              >
                Download Excel
              </button>
              <button
                onClick={() => downloadDocx(selectedRun.id, selectedRun.ritm_number)}
                className="rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500"
              >
                Download Word POA
              </button>
            </div>
          </div>

          {selectedRun.warnings.length > 0 && (
            <div className="border-b border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-400">
              <ul className="list-disc space-y-1 pl-4">
                {selectedRun.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/[0.08] text-left text-zinc-500">
                  <th className="px-3 py-2 font-medium">Source IP</th>
                  <th className="px-3 py-2 font-medium">Destination IP</th>
                  <th className="px-3 py-2 font-medium">Port</th>
                  <th className="px-3 py-2 font-medium">SRC Location</th>
                  <th className="px-3 py-2 font-medium">DST Location</th>
                  <th className="px-3 py-2 font-medium">Src Firewall</th>
                  <th className="px-3 py-2 font-medium">Dst Firewall</th>
                  <th className="px-3 py-2 font-medium">Routing</th>
                </tr>
              </thead>
              <tbody>
                {selectedRun.rows.map((row, i) => {
                  const flagged = Boolean(row["Input Validation"]);
                  return (
                    <tr key={i} className={`border-b border-white/[0.05] ${flagged ? "bg-red-500/10" : ""}`}>
                      <td className="px-3 py-1.5">{row["Source IP"]}</td>
                      <td className="px-3 py-1.5">{row["Destination IP"]}</td>
                      <td className="px-3 py-1.5">{row["Destination Port"]}</td>
                      <td className="px-3 py-1.5">{row["SRC Location"]}</td>
                      <td className="px-3 py-1.5">{row["DST Location"]}</td>
                      <td className="px-3 py-1.5">{row["Source Firewall Name"]}</td>
                      <td className="px-3 py-1.5">{row["Destination Firewall Name"]}</td>
                      <td className="px-3 py-1.5">{row["Routing Availibility"]}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default function AutomationPage() {
  const [tab, setTab] = useState<"hub" | "poa">("hub");

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold text-zinc-50">Automation</h1>
      <div className="mb-6 flex gap-2 border-b border-white/[0.08]">
        {(["hub", "poa"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === t ? "border-indigo-500 text-zinc-50" : "border-transparent text-zinc-500"
            }`}
          >
            {t === "hub" ? "All changes" : "POA generator"}
          </button>
        ))}
      </div>
      {tab === "hub" ? <ChangesHubTab /> : <PoaGeneratorTab />}
    </div>
  );
}
