"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

// TCPWave IPAM sync — pulls the ONPREM team's network/subnet/IP inventory
// from their TCPWave IPAM/DDI instance into NetSphere's own networks/
// subnets/ip_addresses tables. See backend app/services/tcpwave_adapter.py
// for the full research writeup on TCPWave's REST API (what's confirmed
// vs. inferred) and app/services/ipam_sync.py for the upsert logic. Every
// number on this page comes from a real sync run against a real device —
// an unreachable host or bad token shows up as an error here, never a
// fabricated result.

type CloudAccount = { id: string; provider: string; account_identifier: string };

type Integration = {
  id: string;
  vendor: string;
  name: string;
  host: string | null;
  port: number;
  verify_tls: boolean;
  auth_mode: string;
  has_token: boolean;
  token_last4: string;
  organization_name: string | null;
  cloud_account_id: string | null;
  is_active: boolean;
  notes: string;
  last_tested_at: string | null;
  last_test_status: "ok" | "error" | null;
  last_test_message: string;
};

type SyncRun = {
  id: string;
  integration_id: string;
  status: "ok" | "error";
  error_message: string;
  networks_seen: number;
  networks_created: number;
  networks_updated: number;
  subnets_seen: number;
  subnets_created: number;
  subnets_updated: number;
  ips_seen: number;
  ips_created: number;
  ips_updated: number;
  created_at: string;
  finished_at: string | null;
};

type IPAddressRow = {
  id: string;
  subnet_id: string;
  ip_address: string;
  status: string;
  hostname: string | null;
  mac_address: string | null;
  assigned_to: string | null;
  external_source: string | null;
  last_synced_at: string | null;
};

const emptyForm = {
  id: null as string | null,
  name: "",
  host: "",
  port: "7443",
  verify_tls: true,
  organization_name: "",
  cloud_account_id: "",
  token: "",
};

export default function IpamSyncPage() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [cloudAccounts, setCloudAccounts] = useState<CloudAccount[]>([]);
  const [runs, setRuns] = useState<Record<string, SyncRun[]>>({});
  const [ips, setIps] = useState<IPAddressRow[]>([]);
  const [ipQuery, setIpQuery] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState<string | null>(null); // integration id currently testing/syncing
  const [error, setError] = useState<string | null>(null);

  function loadIntegrations() {
    api.get<Integration[]>("/ipam-integrations").then((rows) => {
      setIntegrations(rows);
      rows.forEach((r) =>
        api
          .get<SyncRun[]>(`/ipam-integrations/${r.id}/sync-runs`)
          .then((runRows) => setRuns((prev) => ({ ...prev, [r.id]: runRows })))
          .catch(() => undefined),
      );
    });
  }

  function loadIps(q?: string) {
    api
      .get<IPAddressRow[]>(`/ipam-integrations/ip-addresses${q ? `?q=${encodeURIComponent(q)}` : ""}`)
      .then(setIps)
      .catch(() => undefined);
  }

  useEffect(() => {
    loadIntegrations();
    loadIps();
    api.get<CloudAccount[]>("/orgs/cloud-accounts").then(setCloudAccounts).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function saveIntegration() {
    setError(null);
    const payload = {
      name: form.name,
      host: form.host,
      port: parseInt(form.port, 10) || 7443,
      verify_tls: form.verify_tls,
      auth_mode: "token",
      organization_name: form.organization_name || null,
      cloud_account_id: form.cloud_account_id || null,
      ...(form.token ? { token: form.token } : {}),
    };
    try {
      if (form.id) {
        await api.patch(`/ipam-integrations/${form.id}`, payload);
      } else {
        await api.post("/ipam-integrations", payload);
      }
      setForm(emptyForm);
      setShowForm(false);
      loadIntegrations();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "save failed");
    }
  }

  async function testIntegration(id: string) {
    setBusy(`test:${id}`);
    setError(null);
    try {
      await api.post(`/ipam-integrations/${id}/test`);
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "test failed");
    } finally {
      loadIntegrations();
      setBusy(null);
    }
  }

  async function syncIntegration(id: string) {
    setBusy(`sync:${id}`);
    setError(null);
    try {
      await api.post(`/ipam-integrations/${id}/sync`);
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "sync failed");
    } finally {
      loadIntegrations();
      loadIps(ipQuery);
      setBusy(null);
    }
  }

  async function deleteIntegration(id: string) {
    if (!confirm("Remove this IPAM integration?")) return;
    await api.delete(`/ipam-integrations/${id}`);
    loadIntegrations();
  }

  function editIntegration(i: Integration) {
    setForm({
      id: i.id, name: i.name, host: i.host ?? "", port: String(i.port), verify_tls: i.verify_tls,
      organization_name: i.organization_name ?? "", cloud_account_id: i.cloud_account_id ?? "", token: "",
    });
    setShowForm(true);
  }

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-50">IPAM Sync</h1>
          <p className="mt-1 max-w-3xl text-sm text-zinc-500">
            Pulls the ONPREM team&apos;s network/subnet/IP inventory from TCPWave IPAM into NetSphere&apos;s own IPAM
            tables via TCPWave&apos;s REST API — networks and subnets land in the regular IPAM view tagged
            &quot;onprem&quot;, and individual IP objects (hostname, MAC, allocation status) populate below.
          </p>
        </div>
        <button
          onClick={() => {
            setForm(emptyForm);
            setShowForm(true);
          }}
          className="rounded-lg bg-indigo-500 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-indigo-400"
        >
          + Add TCPWave integration
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      {integrations.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/[0.08] bg-surface-2 p-8 text-sm text-zinc-500">
          No TCPWave integration configured yet. Add one with the host and API token/session token your ONPREM team's
          TCPWave admin console issued, plus which on-prem cloud account (Orgs → Cloud Accounts, provider
          &quot;onprem&quot;) discovered networks should attach under.
        </div>
      ) : (
        <div className="mb-6 space-y-4">
          {integrations.map((i) => {
            const account = cloudAccounts.find((a) => a.id === i.cloud_account_id);
            const history = runs[i.id] ?? [];
            const latest = history[0];
            return (
              <div key={i.id} className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium text-zinc-100">{i.name}</h3>
                      <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-400">
                        {i.vendor}
                      </span>
                      {!i.is_active && (
                        <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-medium text-zinc-500">inactive</span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-zinc-500">
                      {i.host}:{i.port} · token {i.has_token ? `•••${i.token_last4}` : "none saved"}
                      {i.organization_name ? ` · org ${i.organization_name}` : ""}
                      {account ? ` · attaches to ${account.provider}/${account.account_identifier}` : " · no cloud account selected"}
                    </p>
                    {i.last_test_status && (
                      <p className={`mt-1 text-xs ${i.last_test_status === "ok" ? "text-emerald-400" : "text-red-400"}`}>
                        last test: {i.last_test_message || i.last_test_status}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => testIntegration(i.id)}
                      disabled={busy === `test:${i.id}`}
                      className="rounded-lg border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-300 hover:bg-white/[0.04] disabled:opacity-50"
                    >
                      {busy === `test:${i.id}` ? "Testing…" : "Test"}
                    </button>
                    <button
                      onClick={() => syncIntegration(i.id)}
                      disabled={busy === `sync:${i.id}`}
                      className="rounded-lg bg-indigo-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-400 disabled:opacity-50"
                    >
                      {busy === `sync:${i.id}` ? "Syncing…" : "Sync now"}
                    </button>
                    <button
                      onClick={() => editIntegration(i)}
                      className="rounded-lg border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-300 hover:bg-white/[0.04]"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => deleteIntegration(i.id)}
                      className="rounded-lg border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-red-400 hover:bg-red-500/10"
                    >
                      Remove
                    </button>
                  </div>
                </div>

                {history.length > 0 && (
                  <div className="mt-3 overflow-x-auto border-t border-white/[0.06] pt-3">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="text-zinc-500">
                          <th className="pb-1 pr-4 font-medium">When</th>
                          <th className="pb-1 pr-4 font-medium">Status</th>
                          <th className="pb-1 pr-4 font-medium">Networks</th>
                          <th className="pb-1 pr-4 font-medium">Subnets</th>
                          <th className="pb-1 pr-4 font-medium">IPs</th>
                          <th className="pb-1 font-medium">Detail</th>
                        </tr>
                      </thead>
                      <tbody>
                        {history.slice(0, 5).map((r) => (
                          <tr key={r.id} className="border-t border-white/[0.04]">
                            <td className="py-1 pr-4 text-zinc-400">{new Date(r.created_at).toLocaleString()}</td>
                            <td className="py-1 pr-4">
                              {r.status === "ok" ? (
                                <span className="text-emerald-400">ok</span>
                              ) : (
                                <span className="text-red-400">error</span>
                              )}
                            </td>
                            <td className="py-1 pr-4 text-zinc-400">
                              {r.networks_seen} ({r.networks_created} new)
                            </td>
                            <td className="py-1 pr-4 text-zinc-400">
                              {r.subnets_seen} ({r.subnets_created} new)
                            </td>
                            <td className="py-1 pr-4 text-zinc-400">
                              {r.ips_seen} ({r.ips_created} new)
                            </td>
                            <td className="py-1 text-zinc-500">{r.error_message}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {latest?.status === "ok" && (
                  <p className="mt-2 text-xs text-zinc-600">
                    Last synced {new Date(latest.finished_at ?? latest.created_at).toLocaleString()}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-200">Synced IP addresses</h2>
          <input
            value={ipQuery}
            onChange={(e) => {
              setIpQuery(e.target.value);
              loadIps(e.target.value);
            }}
            placeholder="search hostname or IP…"
            className="w-64 rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1 text-xs text-zinc-200 placeholder:text-zinc-600"
          />
        </div>
        {ips.length === 0 ? (
          <p className="text-sm text-zinc-500">No IP objects synced yet — run a sync above.</p>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-surface-2">
                <tr className="text-xs uppercase tracking-wide text-zinc-500">
                  <th className="pb-2 pr-4 font-medium">IP address</th>
                  <th className="pb-2 pr-4 font-medium">Hostname</th>
                  <th className="pb-2 pr-4 font-medium">MAC</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 pr-4 font-medium">Owner/org</th>
                  <th className="pb-2 font-medium">Last synced</th>
                </tr>
              </thead>
              <tbody>
                {ips.map((ip) => (
                  <tr key={ip.id} className="border-t border-white/[0.06]">
                    <td className="py-1.5 pr-4 font-mono text-zinc-200">{ip.ip_address}</td>
                    <td className="py-1.5 pr-4 text-zinc-300">{ip.hostname ?? "—"}</td>
                    <td className="py-1.5 pr-4 font-mono text-xs text-zinc-500">{ip.mac_address ?? "—"}</td>
                    <td className="py-1.5 pr-4 text-zinc-400">{ip.status}</td>
                    <td className="py-1.5 pr-4 text-zinc-400">{ip.assigned_to ?? "—"}</td>
                    <td className="py-1.5 text-zinc-500">
                      {ip.last_synced_at ? new Date(ip.last_synced_at).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setShowForm(false)}>
          <div
            className="w-full max-w-lg rounded-2xl border border-white/[0.08] bg-surface-2 p-5 shadow-elevated"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-4 text-sm font-semibold text-zinc-100">
              {form.id ? "Edit TCPWave integration" : "Add TCPWave integration"}
            </h3>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-zinc-500">Name</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200"
                />
              </div>
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="mb-1 block text-xs font-medium text-zinc-500">Host</label>
                  <input
                    value={form.host}
                    onChange={(e) => setForm((f) => ({ ...f, host: e.target.value }))}
                    placeholder="tcpwave.bfl.internal"
                    className="w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600"
                  />
                </div>
                <div className="w-24">
                  <label className="mb-1 block text-xs font-medium text-zinc-500">Port</label>
                  <input
                    value={form.port}
                    onChange={(e) => setForm((f) => ({ ...f, port: e.target.value }))}
                    className="w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-zinc-500">
                  Session token {form.id ? "(leave blank to keep existing)" : ""}
                </label>
                <input
                  type="password"
                  value={form.token}
                  onChange={(e) => setForm((f) => ({ ...f, token: e.target.value }))}
                  placeholder="minted via TCPWave's auth_token/get, or from the TIMS admin console"
                  className="w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-zinc-500">Organization filter (optional)</label>
                <input
                  value={form.organization_name}
                  onChange={(e) => setForm((f) => ({ ...f, organization_name: e.target.value }))}
                  placeholder="leave blank to pull every organization"
                  className="w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-zinc-500">Attach discovered networks to</label>
                <select
                  value={form.cloud_account_id}
                  onChange={(e) => setForm((f) => ({ ...f, cloud_account_id: e.target.value }))}
                  className="w-full rounded-lg border border-white/[0.08] bg-surface-1 px-3 py-1.5 text-sm text-zinc-200"
                >
                  <option value="">Select a cloud account…</option>
                  {cloudAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.provider}/{a.account_identifier}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-zinc-600">
                  No &quot;onprem&quot; account yet? Create one under Orgs → Cloud Accounts first (provider =
                  &quot;onprem&quot;).
                </p>
              </div>
              <label className="flex items-center gap-2 text-xs text-zinc-400">
                <input
                  type="checkbox"
                  checked={form.verify_tls}
                  onChange={(e) => setForm((f) => ({ ...f, verify_tls: e.target.checked }))}
                />
                Verify TLS certificate
              </label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setShowForm(false)}
                className="rounded-lg border border-white/[0.08] px-3 py-1.5 text-sm text-zinc-300 hover:bg-white/[0.04]"
              >
                Cancel
              </button>
              <button
                onClick={saveIntegration}
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
