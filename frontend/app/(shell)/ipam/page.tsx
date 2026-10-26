"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Network = {
  id: string;
  name: string;
  cidr: string;
  provider: string;
  region: string | null;
  owner_team: string | null;
  environment_name: string | null;
  firewall: string | null;
  status: string;
  subnet_count: number;
  overlap_warnings?: OverlapWarning[] | null;
};

type Subnet = {
  id: string;
  network_id: string;
  name: string | null;
  cidr: string;
  availability_zone: string | null;
  owner_team: string | null;
  application: string | null;
  status: string;
};

type FreeSpace = { total_addresses: number; total_free: number; free: { range: string; addresses: number }[] };

type Preview = { suggested_cidr: string; prefix_len: number; usable_hosts: number; hosts: number };

type Conflict = {
  type: string;
  cross_provider: boolean;
  a: { cidr: string; provider: string };
  b: { cidr: string; provider: string };
};

type OverlapWarning = {
  type: string;
  cross_provider: boolean;
  network: { id: string; cidr: string; provider: string; name: string; owner_team: string | null };
};

type ImportRowResult = {
  row: number;
  status: "created" | "updated" | "error";
  message: string | null;
  cidr: string | null;
  name: string | null;
  overlap_warnings: OverlapWarning[] | null;
};

type ImportSummary = { created: number; updated: number; errors: number; rows: ImportRowResult[] };

type SearchMatch = {
  kind: "network" | "subnet";
  id: string;
  cidr: string;
  prefix_len: number;
  owner_team: string | null;
  // network-only
  provider?: string;
  environment?: string | null;
  region?: string | null;
  // subnet-only
  network_id?: string;
  application?: string | null;
};

type SearchResponse = { ip: string; matches: SearchMatch[]; best_match: SearchMatch | null };

function MatchRow({ match, isBest }: { match: SearchMatch; isBest: boolean }) {
  return (
    <li className={`rounded-xl border px-3 py-2 text-sm ${isBest ? "border-indigo-700 bg-indigo-500/10" : "border-white/[0.08] bg-surface-2"}`}>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
              match.kind === "network" ? "bg-white/[0.1] text-zinc-500" : "bg-sky-100 text-sky-700"
            }`}
          >
            {match.kind}
          </span>
          <span className="font-mono font-medium text-zinc-100">{match.cidr}</span>
          {isBest && <span className="text-[10px] font-semibold uppercase text-indigo-400">best match</span>}
        </span>
        <span className="text-xs text-zinc-500">/{match.prefix_len}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-zinc-500">
        {match.kind === "network" && (
          <>
            <span>provider: {match.provider}</span>
            {match.region && <span>region: {match.region}</span>}
            {match.environment && <span>env: {match.environment}</span>}
          </>
        )}
        {match.kind === "subnet" && match.application && <span>application: {match.application}</span>}
        <span>owner: {match.owner_team ?? "—"}</span>
      </div>
    </li>
  );
}

export default function IpamPage() {
  const [networks, setNetworks] = useState<Network[]>([]);
  const [selected, setSelected] = useState<Network | null>(null);
  const [subnets, setSubnets] = useState<Subnet[]>([]);
  const [freeSpace, setFreeSpace] = useState<FreeSpace | null>(null);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);

  const [hosts, setHosts] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [allocError, setAllocError] = useState<string | null>(null);
  const [ownerTeam, setOwnerTeam] = useState("");
  const [application, setApplication] = useState("");

  const [searchIp, setSearchIp] = useState("");
  const [searchResult, setSearchResult] = useState<SearchResponse | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [editCidr, setEditCidr] = useState("");
  const [editName, setEditName] = useState("");
  const [editFirewall, setEditFirewall] = useState("");
  const [editEnvironment, setEditEnvironment] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [editSaving, setEditSaving] = useState(false);
  const [editOverlapWarnings, setEditOverlapWarnings] = useState<OverlapWarning[] | null>(null);

  const [importSummary, setImportSummary] = useState<ImportSummary | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);

  async function loadNetworks() {
    const rows = await api.get<Network[]>("/ipam/networks");
    setNetworks(rows);
  }

  async function loadConflicts() {
    const { conflicts } = await api.get<{ conflicts: Conflict[] }>("/ipam/overlaps");
    setConflicts(conflicts);
  }

  useEffect(() => {
    loadNetworks().catch(() => {});
    loadConflicts().catch(() => {});
  }, []);

  async function selectNetwork(n: Network) {
    setSelected(n);
    setPreview(null);
    setAllocError(null);
    setEditing(false);
    setEditError(null);
    setEditOverlapWarnings(null);
    setEditCidr(n.cidr);
    setEditName(n.name);
    setEditFirewall(n.firewall ?? "");
    setEditEnvironment(n.environment_name ?? "");
    const [subs, fs] = await Promise.all([
      api.get<Subnet[]>(`/ipam/networks/${n.id}/subnets`),
      api.get<FreeSpace>(`/ipam/networks/${n.id}/free-space`),
    ]);
    setSubnets(subs);
    setFreeSpace(fs);
  }

  async function saveNetworkEdit() {
    if (!selected) return;
    setEditSaving(true);
    setEditError(null);
    setEditOverlapWarnings(null);
    try {
      const updated = await api.patch<Network>(`/ipam/networks/${selected.id}`, {
        cidr: editCidr,
        name: editName,
        firewall: editFirewall || null,
        environment_name: editEnvironment || null,
      });
      setSelected(updated);
      setEditing(false);
      setEditOverlapWarnings(updated.overlap_warnings ?? null);
      await loadNetworks();
      await loadConflicts();
    } catch (e) {
      setEditError(e instanceof ApiError ? JSON.stringify(e.detail) : "update failed");
    } finally {
      setEditSaving(false);
    }
  }

  async function doExport() {
    setExporting(true);
    try {
      await api.downloadFile("/ipam/networks/export", "netsphere_networks_export.csv");
    } catch (e) {
      setImportError(e instanceof ApiError ? JSON.stringify(e.detail) : "export failed");
    } finally {
      setExporting(false);
    }
  }

  async function doImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file name later
    if (!file) return;
    setImporting(true);
    setImportError(null);
    setImportSummary(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const summary = await api.postForm<ImportSummary>("/ipam/networks/import", form);
      setImportSummary(summary);
      await loadNetworks();
      await loadConflicts();
    } catch (e) {
      setImportError(e instanceof ApiError ? JSON.stringify(e.detail) : "import failed");
    } finally {
      setImporting(false);
    }
  }

  async function doPreview() {
    if (!selected || !hosts) return;
    setAllocError(null);
    try {
      const p = await api.get<Preview>(`/ipam/networks/${selected.id}/allocate/preview?hosts=${hosts}`);
      setPreview(p);
    } catch (e) {
      setPreview(null);
      setAllocError(e instanceof ApiError ? JSON.stringify(e.detail) : "preview failed");
    }
  }

  async function doAllocate() {
    if (!selected || !hosts) return;
    setAllocError(null);
    try {
      await api.post(`/ipam/networks/${selected.id}/allocate`, {
        hosts: Number(hosts),
        owner_team: ownerTeam || undefined,
        application: application || undefined,
      });
      setHosts("");
      setOwnerTeam("");
      setApplication("");
      setPreview(null);
      await selectNetwork(selected);
      await loadNetworks();
      await loadConflicts();
    } catch (e) {
      setAllocError(e instanceof ApiError ? JSON.stringify(e.detail) : "allocate failed");
    }
  }

  async function doSearch(e: React.FormEvent) {
    e.preventDefault();
    setSearchError(null);
    setSearchResult(null);
    try {
      setSearchResult(await api.get<SearchResponse>(`/ipam/search?ip=${encodeURIComponent(searchIp)}`));
    } catch (e) {
      setSearchError(e instanceof ApiError ? String(e.detail) : "search failed");
    }
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold text-zinc-50">IPAM</h1>
      <p className="mb-6 text-sm text-zinc-500">Networks, subnets, IP search, overlap detection, and automatic allocation</p>

      <div className="mb-6 rounded-xl border border-white/[0.08] bg-surface-2 p-4">
        <form onSubmit={doSearch} className="flex gap-2">
          <input
            className="flex-1 rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
            placeholder="Search an IP, e.g. 10.10.0.5"
            value={searchIp}
            onChange={(e) => setSearchIp(e.target.value)}
          />
          <button className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white">Search</button>
        </form>

        {searchError && <p className="mt-3 text-sm text-red-400">{searchError}</p>}

        {searchResult && (
          <div className="mt-3">
            {searchResult.matches.length === 0 ? (
              <p className="text-sm text-zinc-500">No network or subnet contains {searchResult.ip}.</p>
            ) : (
              <>
                <p className="mb-2 text-xs uppercase tracking-wide text-zinc-500">
                  {searchResult.matches.length} match{searchResult.matches.length === 1 ? "" : "es"} for {searchResult.ip}, most specific first
                </p>
                <ul className="space-y-1.5">
                  {searchResult.matches.map((m) => (
                    <MatchRow key={`${m.kind}-${m.id}`} match={m} isBest={m.id === searchResult.best_match?.id && m.kind === searchResult.best_match?.kind} />
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </div>

      {conflicts.length > 0 && (
        <div className="mb-6 rounded-xl border border-amber-700 bg-amber-500/10 p-4 text-sm text-amber-400">
          <p className="font-medium">{conflicts.length} overlapping network{conflicts.length === 1 ? "" : "s"} detected</p>
          <ul className="mt-2 list-disc pl-5">
            {conflicts.map((c, i) => (
              <li key={i}>
                {c.type === "duplicate" ? "Duplicate range" : "Nested"}: {c.a.cidr} ({c.a.provider}) vs {c.b.cidr} ({c.b.provider})
                {c.cross_provider && " — cross-provider"}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-white/[0.08] bg-surface-2">
          <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-3">
            <span className="text-sm font-medium text-zinc-600">Networks</span>
            <div className="flex items-center gap-2">
              <button
                onClick={doExport}
                disabled={exporting}
                className="rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500 disabled:opacity-40"
              >
                {exporting ? "Exporting…" : "Export CSV"}
              </button>
              <label className="cursor-pointer rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500">
                {importing ? "Importing…" : "Import CSV"}
                <input type="file" accept=".csv,text/csv" onChange={doImport} disabled={importing} className="hidden" />
              </label>
            </div>
          </div>

          {importError && <p className="border-b border-white/[0.08] px-4 py-2 text-sm text-red-400">{importError}</p>}

          {importSummary && (
            <div className="border-b border-white/[0.08] bg-white/[0.04] px-4 py-3 text-sm">
              <p className="font-medium text-zinc-600">
                Import complete: {importSummary.created} created, {importSummary.updated} updated
                {importSummary.errors > 0 && `, ${importSummary.errors} failed`}
              </p>
              {importSummary.rows.some((r) => r.status === "error" || (r.overlap_warnings && r.overlap_warnings.length > 0)) && (
                <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs">
                  {importSummary.rows
                    .filter((r) => r.status === "error" || (r.overlap_warnings && r.overlap_warnings.length > 0))
                    .map((r) => (
                      <li key={r.row} className={r.status === "error" ? "text-red-400" : "text-amber-400"}>
                        Row {r.row}
                        {r.status === "error"
                          ? `: ${r.message}`
                          : `: ${r.cidr} overlaps ${r.overlap_warnings!.length} existing network${r.overlap_warnings!.length === 1 ? "" : "s"}`}
                      </li>
                    ))}
                </ul>
              )}
              <button onClick={() => setImportSummary(null)} className="mt-2 text-xs text-zinc-500 underline">
                Dismiss
              </button>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-zinc-500">
                <tr>
                  <th className="px-4 py-2">CIDR</th>
                  <th className="px-4 py-2">Name</th>
                  <th className="px-4 py-2">Firewall</th>
                  <th className="px-4 py-2">Environment</th>
                  <th className="px-4 py-2">Provider</th>
                  <th className="px-4 py-2">Region</th>
                  <th className="px-4 py-2">Owner team</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Subnets</th>
                </tr>
              </thead>
              <tbody>
                {networks.map((n) => (
                  <tr
                    key={n.id}
                    onClick={() => selectNetwork(n)}
                    className={`cursor-pointer border-t border-white/[0.08] hover:bg-white/[0.04] ${
                      selected?.id === n.id ? "bg-indigo-500/10" : ""
                    }`}
                  >
                    <td className="whitespace-nowrap px-4 py-2 font-mono font-medium text-zinc-100">{n.cidr}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-zinc-500">{n.name}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-zinc-500">{n.firewall ?? "—"}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-zinc-500">{n.environment_name ?? "—"}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-zinc-500">{n.provider}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-zinc-500">{n.region ?? "—"}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-zinc-500">{n.owner_team ?? "—"}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-zinc-500">{n.status}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-zinc-500">{n.subnet_count}</td>
                  </tr>
                ))}
                {networks.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-6 text-center text-zinc-500">
                      No networks yet — run discovery from the API or create one directly.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4">
          {!selected && <p className="text-sm text-zinc-500">Select a network to see its subnets and allocate from its free space.</p>}
          {selected && (
            <>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-zinc-300"><span className="font-mono">{selected.cidr}</span> — subnets</h2>
                {!editing && (
                  <button
                    onClick={() => setEditing(true)}
                    className="rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500"
                  >
                    Edit network
                  </button>
                )}
              </div>

              {!editing && editOverlapWarnings && editOverlapWarnings.length > 0 && (
                <div className="mb-4 rounded-xl border border-amber-700 bg-amber-500/10 p-3 text-sm text-amber-400">
                  <p className="font-medium">
                    {editOverlapWarnings.length} overlap{editOverlapWarnings.length === 1 ? "" : "s"} with this network's new CIDR
                  </p>
                  <ul className="mt-1 list-disc pl-5">
                    {editOverlapWarnings.map((w, i) => (
                      <li key={i}>
                        {w.type === "duplicate" ? "Duplicate of" : "Nested with"} {w.network.cidr} ({w.network.provider}, {w.network.name})
                        {w.cross_provider && " — cross-provider"}
                      </li>
                    ))}
                  </ul>
                  <button onClick={() => setEditOverlapWarnings(null)} className="mt-1 text-xs text-amber-400 underline">
                    Dismiss
                  </button>
                </div>
              )}

              {editing && (
                <div className="mb-4 rounded-xl border border-white/[0.08] bg-white/[0.04] p-3">
                  <p className="mb-2 text-xs font-semibold uppercase text-zinc-500">Edit network</p>
                  <div className="mb-2 grid grid-cols-2 gap-2">
                    <label className="text-xs text-zinc-500">
                      CIDR
                      <input
                        className="mt-0.5 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-2 py-1.5 text-sm text-zinc-100"
                        value={editCidr}
                        onChange={(e) => setEditCidr(e.target.value)}
                      />
                    </label>
                    <label className="text-xs text-zinc-500">
                      Name
                      <input
                        className="mt-0.5 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-2 py-1.5 text-sm text-zinc-100"
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                      />
                    </label>
                    <label className="text-xs text-zinc-500">
                      Firewall
                      <input
                        className="mt-0.5 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-2 py-1.5 text-sm text-zinc-100"
                        placeholder="e.g. fw-prod-01"
                        value={editFirewall}
                        onChange={(e) => setEditFirewall(e.target.value)}
                      />
                    </label>
                    <label className="text-xs text-zinc-500">
                      Environment
                      <input
                        className="mt-0.5 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-2 py-1.5 text-sm text-zinc-100"
                        value={editEnvironment}
                        onChange={(e) => setEditEnvironment(e.target.value)}
                      />
                    </label>
                  </div>
                  {editError && <p className="mb-2 text-sm text-red-400">{editError}</p>}
                  <div className="flex gap-2">
                    <button
                      onClick={saveNetworkEdit}
                      disabled={editSaving}
                      className="rounded-xl bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
                    >
                      {editSaving ? "Saving…" : "Save"}
                    </button>
                    <button
                      onClick={() => {
                        setEditing(false);
                        setEditError(null);
                      }}
                      className="rounded-xl border border-white/[0.08] px-3 py-1.5 text-sm text-zinc-500"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              <ul className="mb-4 space-y-1 text-sm">
                {subnets.map((s) => (
                  <li key={s.id} className="flex justify-between rounded bg-white/[0.04] px-3 py-1.5">
                    <span>{s.cidr}</span>
                    <span className="text-zinc-500">{s.owner_team ?? "—"}</span>
                  </li>
                ))}
                {subnets.length === 0 && <li className="text-zinc-500">No subnets yet.</li>}
              </ul>

              {freeSpace && (
                <p className="mb-4 text-xs text-zinc-500">
                  {freeSpace.total_free.toLocaleString()} of {freeSpace.total_addresses.toLocaleString()} addresses free
                </p>
              )}

              <div className="rounded-xl border border-white/[0.08] p-3">
                <p className="mb-2 text-xs font-semibold uppercase text-zinc-500">Allocate IP</p>
                <div className="mb-2 flex gap-2">
                  <input
                    type="number"
                    min={1}
                    placeholder="Machines required"
                    className="w-40 rounded-xl border border-white/[0.08] bg-surface-1 px-2 py-1.5 text-sm text-zinc-100"
                    value={hosts}
                    onChange={(e) => {
                      setHosts(e.target.value);
                      setPreview(null);
                    }}
                  />
                  <button onClick={doPreview} className="rounded-xl border border-white/[0.08] px-3 py-1.5 text-sm">
                    Preview
                  </button>
                </div>
                <div className="mb-2 flex gap-2">
                  <input
                    placeholder="Owner/team"
                    className="flex-1 rounded-xl border border-white/[0.08] bg-surface-1 px-2 py-1.5 text-sm text-zinc-100"
                    value={ownerTeam}
                    onChange={(e) => setOwnerTeam(e.target.value)}
                  />
                  <input
                    placeholder="Application"
                    className="flex-1 rounded-xl border border-white/[0.08] bg-surface-1 px-2 py-1.5 text-sm text-zinc-100"
                    value={application}
                    onChange={(e) => setApplication(e.target.value)}
                  />
                </div>
                {preview && (
                  <p className="mb-2 text-sm text-emerald-400">
                    Suggested: <strong>{preview.suggested_cidr}</strong> (/{preview.prefix_len}, {preview.usable_hosts} usable)
                  </p>
                )}
                {allocError && <p className="mb-2 text-sm text-red-400">{allocError}</p>}
                <button
                  onClick={doAllocate}
                  disabled={!preview}
                  className="rounded-xl bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-40"
                >
                  Allocate
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
