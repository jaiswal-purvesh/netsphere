"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

// Secure credential store for the firewall-automation pipeline (see
// claude/firewall-policy-automation-design.md and
// claude/panorama-executor-implementation.md's fwauto executor): every API
// key/token the future execution automation needs lives here in one place,
// encrypted at rest server-side. The API never returns a decrypted secret —
// only `has_secret` + a masked last-4 — so this page always shows secrets
// as dots, never the real value.

type Vendor = "panorama" | "pan_os" | "fortigate" | "ngfw";

type Integration = {
  id: string;
  vendor: Vendor;
  name: string;
  host: string | null;
  port: number;
  verify_tls: boolean;
  auth_type: string | null;
  username: string | null;
  has_secret: boolean;
  secret_last4: string;
  device_group: string | null;
  serial: string | null;
  parent_id: string | null;
  is_active: boolean;
  notes: string;
  last_tested_at: string | null;
  last_test_status: "ok" | "error" | null;
  last_test_message: string;
  children: Integration[];
};

const VENDOR_SECTIONS: { vendor: Vendor; title: string; blurb: string }[] = [
  { vendor: "panorama", title: "Panorama", blurb: "Manages the Palo Alto NGFWs listed under each entry below." },
  { vendor: "pan_os", title: "PAN-OS (on-prem, e.g. PA-5260)", blurb: "A standalone firewall not managed by Panorama." },
  { vendor: "fortigate", title: "FortiGate", blurb: "Direct FortiOS REST API access." },
];

// --- Cloud integrations (AWS/Azure/GCP/OCI) — feed live discovery -------
// Saving a credential here is what turns the account it matches (by
// vendor + account identifier) from mock demo data into live discovery
// results the next time that account's "Discover" is run — see
// backend app/api/v1/endpoints/discovery.py's _resolve_provider.

type CloudVendor = "aws" | "azure" | "gcp" | "oci";

type CloudIntegrationRow = {
  id: string;
  vendor: CloudVendor;
  name: string;
  account_identifier: string;
  region_default: string | null;
  has_credentials: boolean;
  credential_summary: string;
  is_active: boolean;
  notes: string;
  last_tested_at: string | null;
  last_test_status: "ok" | "error" | null;
  last_test_message: string;
};

const CLOUD_SECTIONS: { vendor: CloudVendor; title: string; idLabel: string; idPlaceholder: string; blurb: string }[] = [
  { vendor: "aws", title: "AWS", idLabel: "Account ID", idPlaceholder: "111111111111", blurb: "Discovers VPCs and subnets via EC2." },
  { vendor: "azure", title: "Azure", idLabel: "Subscription ID", idPlaceholder: "00000000-0000-0000-0000-000000000000", blurb: "Discovers VNets and subnets via Network Management." },
  { vendor: "gcp", title: "GCP", idLabel: "Project ID", idPlaceholder: "my-project-123", blurb: "Discovers VPCs and subnetworks via Compute Engine." },
  { vendor: "oci", title: "OCI", idLabel: "Compartment OCID", idPlaceholder: "ocid1.compartment.oc1..", blurb: "Discovers VCNs and subnets via the Virtual Network API." },
];

type CloudFormState = {
  id: string | null;
  vendor: CloudVendor;
  name: string;
  account_identifier: string;
  region_default: string;
  notes: string;
  // AWS
  auth_mode: "access_key" | "role_arn";
  access_key_id: string;
  secret_access_key: string;
  role_arn: string;
  external_id: string;
  // Azure
  tenant_id: string;
  client_id: string;
  client_secret: string;
  // GCP
  service_account_json: string;
  // OCI
  user_ocid: string;
  tenancy_ocid: string;
  fingerprint: string;
  private_key_pem: string;
  region: string;
};

function blankCloudForm(vendor: CloudVendor): CloudFormState {
  return {
    id: null, vendor, name: "", account_identifier: "", region_default: "", notes: "",
    auth_mode: "access_key", access_key_id: "", secret_access_key: "", role_arn: "", external_id: "",
    tenant_id: "", client_id: "", client_secret: "",
    service_account_json: "",
    user_ocid: "", tenancy_ocid: "", fingerprint: "", private_key_pem: "", region: "",
  };
}

function CloudStatusBadge({ row }: { row: CloudIntegrationRow }) {
  if (!row.last_tested_at) {
    return <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-xs font-medium text-zinc-500 ring-1 ring-inset ring-white/[0.1]">not tested</span>;
  }
  const ok = row.last_test_status === "ok";
  return (
    <span
      title={row.last_test_message}
      className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${ok ? "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30" : "bg-red-500/10 text-red-400 ring-red-500/30"}`}
    >
      {ok ? "reachable" : "failed"}
    </span>
  );
}

type FormState = {
  id: string | null;
  vendor: Vendor;
  name: string;
  host: string;
  port: string;
  verify_tls: boolean;
  auth_type: "api_key" | "username_password";
  username: string;
  secret: string;
  device_group: string;
  serial: string;
  parent_id: string;
  notes: string;
};

function blankForm(vendor: Vendor, parent_id = ""): FormState {
  return {
    id: null, vendor, name: "", host: "", port: "443", verify_tls: true,
    auth_type: "api_key", username: "", secret: "", device_group: "", serial: "", parent_id, notes: "",
  };
}

function StatusBadge({ integration }: { integration: Integration }) {
  if (!integration.last_tested_at) {
    return <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-xs font-medium text-zinc-500 ring-1 ring-inset ring-white/[0.1]">not tested</span>;
  }
  const ok = integration.last_test_status === "ok";
  return (
    <span
      title={integration.last_test_message}
      className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
        ok ? "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30" : "bg-red-500/10 text-red-400 ring-red-500/30"
      }`}
    >
      {ok ? "reachable" : "failed"}
    </span>
  );
}

export default function IntegrationsPage() {
  const [items, setItems] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [cloudItems, setCloudItems] = useState<CloudIntegrationRow[]>([]);
  const [cloudTestingId, setCloudTestingId] = useState<string | null>(null);
  const [cloudForm, setCloudForm] = useState<CloudFormState | null>(null);
  const [cloudSaving, setCloudSaving] = useState(false);
  const [cloudFormError, setCloudFormError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [fw, cloud] = await Promise.all([
        api.get<Integration[]>("/integrations"),
        api.get<CloudIntegrationRow[]>("/cloud-integrations"),
      ]);
      setItems(fw);
      setCloudItems(cloud);
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "could not load integrations");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function openCloudCreate(vendor: CloudVendor) {
    setCloudFormError(null);
    setCloudForm(blankCloudForm(vendor));
  }

  function openCloudEdit(row: CloudIntegrationRow) {
    setCloudFormError(null);
    setCloudForm({
      ...blankCloudForm(row.vendor),
      id: row.id, name: row.name, account_identifier: row.account_identifier,
      region_default: row.region_default ?? "", notes: row.notes,
    });
  }

  function credentialsFromCloudForm(f: CloudFormState): Record<string, string> {
    switch (f.vendor) {
      case "aws":
        return f.auth_mode === "access_key"
          ? { auth_mode: "access_key", access_key_id: f.access_key_id, secret_access_key: f.secret_access_key }
          : { auth_mode: "role_arn", role_arn: f.role_arn, ...(f.external_id ? { external_id: f.external_id } : {}) };
      case "azure":
        return {
          tenant_id: f.tenant_id, client_id: f.client_id, client_secret: f.client_secret,
          subscription_id: f.account_identifier,
        };
      case "gcp":
        return { service_account_json: f.service_account_json };
      case "oci":
        return {
          user_ocid: f.user_ocid, tenancy_ocid: f.tenancy_ocid, fingerprint: f.fingerprint,
          private_key_pem: f.private_key_pem, region: f.region,
        };
    }
  }

  function cloudCredentialsFieldsFilled(f: CloudFormState): boolean {
    switch (f.vendor) {
      case "aws":
        return f.auth_mode === "access_key" ? !!(f.access_key_id && f.secret_access_key) : !!f.role_arn;
      case "azure":
        return !!(f.tenant_id && f.client_id && f.client_secret);
      case "gcp":
        return !!f.service_account_json;
      case "oci":
        return !!(f.user_ocid && f.tenancy_ocid && f.fingerprint && f.private_key_pem);
    }
  }

  async function onCloudSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!cloudForm) return;
    setCloudSaving(true);
    setCloudFormError(null);
    try {
      const includeCredentials = !cloudForm.id || cloudCredentialsFieldsFilled(cloudForm);
      if (cloudForm.id) {
        await api.patch(`/cloud-integrations/${cloudForm.id}`, {
          name: cloudForm.name, region_default: cloudForm.region_default || null, notes: cloudForm.notes,
          ...(includeCredentials ? { credentials: credentialsFromCloudForm(cloudForm) } : {}),
        });
      } else {
        await api.post("/cloud-integrations", {
          vendor: cloudForm.vendor, name: cloudForm.name, account_identifier: cloudForm.account_identifier,
          region_default: cloudForm.region_default || null, notes: cloudForm.notes,
          credentials: credentialsFromCloudForm(cloudForm),
        });
      }
      setCloudForm(null);
      await load();
    } catch (e) {
      setCloudFormError(e instanceof ApiError ? String(e.detail) : "save failed");
    } finally {
      setCloudSaving(false);
    }
  }

  async function onCloudDelete(row: CloudIntegrationRow) {
    if (!window.confirm(`Remove "${row.name}"? This can't be undone.`)) return;
    try {
      await api.delete(`/cloud-integrations/${row.id}`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "delete failed");
    }
  }

  async function onCloudTest(row: CloudIntegrationRow) {
    setCloudTestingId(row.id);
    try {
      await api.post(`/cloud-integrations/${row.id}/test`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "test failed");
    } finally {
      setCloudTestingId(null);
    }
  }

  const cloudByVendor = (v: CloudVendor) => cloudItems.filter((i) => i.vendor === v);

  function openCreate(vendor: Vendor, parent_id = "") {
    setFormError(null);
    setForm(blankForm(vendor, parent_id));
  }

  function openEdit(item: Integration) {
    setFormError(null);
    setForm({
      id: item.id, vendor: item.vendor, name: item.name, host: item.host ?? "",
      port: String(item.port), verify_tls: item.verify_tls,
      auth_type: (item.auth_type as FormState["auth_type"]) ?? "api_key",
      username: item.username ?? "", secret: "", device_group: item.device_group ?? "",
      serial: item.serial ?? "", parent_id: item.parent_id ?? "", notes: item.notes,
    });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    setFormError(null);
    try {
      if (form.id) {
        await api.patch(`/integrations/${form.id}`, {
          name: form.name, host: form.host || null, port: Number(form.port),
          verify_tls: form.verify_tls, auth_type: form.vendor === "ngfw" ? null : form.auth_type,
          username: form.username || null, secret: form.secret || undefined,
          device_group: form.device_group || null, serial: form.serial || null, notes: form.notes,
        });
      } else {
        await api.post("/integrations", {
          vendor: form.vendor, name: form.name, host: form.host || null, port: Number(form.port),
          verify_tls: form.verify_tls, auth_type: form.vendor === "ngfw" ? null : form.auth_type,
          username: form.username || null, secret: form.secret || null,
          device_group: form.device_group || null, serial: form.serial || null,
          parent_id: form.parent_id || null, notes: form.notes,
        });
      }
      setForm(null);
      await load();
    } catch (e) {
      setFormError(e instanceof ApiError ? String(e.detail) : "save failed");
    } finally {
      setSaving(false);
    }
  }

  async function onDelete(item: Integration) {
    if (!window.confirm(`Remove "${item.name}"? This can't be undone.`)) return;
    try {
      await api.delete(`/integrations/${item.id}`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "delete failed");
    }
  }

  async function onTest(item: Integration) {
    setTestingId(item.id);
    try {
      await api.post(`/integrations/${item.id}/test`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "test failed");
    } finally {
      setTestingId(null);
    }
  }

  const byVendor = (v: Vendor) => items.filter((i) => i.vendor === v);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-zinc-50">Integrations</h2>
        <p className="text-sm text-zinc-500">
          Manage the API keys the firewall-automation pipeline uses to talk to Panorama, on-prem PAN-OS
          firewalls, and FortiGate — kept encrypted at rest and never shown back once saved.
        </p>
      </div>

      {error && <p className="rounded-xl border border-red-900 bg-red-500/10 px-3 py-2 text-sm text-red-400">{error}</p>}
      {loading && <p className="text-sm text-zinc-500">Loading…</p>}

      {!loading &&
        VENDOR_SECTIONS.map((section) => {
          const rows = byVendor(section.vendor);
          return (
            <div key={section.vendor} className="rounded-xl border border-white/[0.08] bg-surface-2">
              <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-3">
                <div>
                  <h3 className="text-sm font-semibold text-zinc-100">{section.title}</h3>
                  <p className="text-xs text-zinc-500">{section.blurb}</p>
                </div>
                <button
                  onClick={() => openCreate(section.vendor)}
                  className="rounded-xl bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500"
                >
                  Add {section.title.split(" ")[0]}
                </button>
              </div>

              {rows.length === 0 ? (
                <p className="px-4 py-4 text-sm text-zinc-500">None configured yet.</p>
              ) : (
                <ul className="divide-y divide-white/[0.06]">
                  {rows.map((item) => (
                    <li key={item.id} className="px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-medium text-zinc-100">{item.name}</span>
                            <StatusBadge integration={item} />
                            {!item.is_active && (
                              <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[11px] text-zinc-500">disabled</span>
                            )}
                          </div>
                          <p className="truncate text-xs text-zinc-500">
                            {item.host}:{item.port} &middot; key ending •••{item.secret_last4 || "····"}
                          </p>
                          {item.last_test_message && item.last_test_status === "error" && (
                            <p className="truncate text-xs text-red-500">{item.last_test_message}</p>
                          )}
                        </div>
                        <div className="flex flex-shrink-0 items-center gap-2">
                          <button
                            onClick={() => onTest(item)}
                            disabled={testingId === item.id}
                            className="rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500 hover:bg-white/[0.04] disabled:opacity-50"
                          >
                            {testingId === item.id ? "Testing…" : "Test"}
                          </button>
                          {section.vendor === "panorama" && (
                            <button
                              onClick={() => openCreate("ngfw", item.id)}
                              className="rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500 hover:bg-white/[0.04]"
                            >
                              + NGFW
                            </button>
                          )}
                          <button
                            onClick={() => openEdit(item)}
                            className="rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500 hover:bg-white/[0.04]"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => onDelete(item)}
                            className="rounded-xl border border-red-900 px-2.5 py-1 text-xs font-medium text-red-400 hover:bg-red-500/10"
                          >
                            Remove
                          </button>
                        </div>
                      </div>

                      {item.children.length > 0 && (
                        <ul className="mt-2 space-y-1.5 border-l-2 border-white/[0.08] pl-3">
                          {item.children.map((child) => (
                            <li key={child.id} className="flex items-center justify-between gap-3">
                              <div className="min-w-0 text-xs text-zinc-500">
                                <span className="font-medium text-zinc-600">{child.name}</span>
                                {" — "}
                                device group <span className="font-mono">{child.device_group || "—"}</span>
                                {child.serial && <> &middot; serial <span className="font-mono">{child.serial}</span></>}
                              </div>
                              <div className="flex flex-shrink-0 gap-2">
                                <button
                                  onClick={() => openEdit(child)}
                                  className="rounded-xl border border-white/[0.08] px-2 py-0.5 text-[11px] font-medium text-zinc-500 hover:bg-white/[0.04]"
                                >
                                  Edit
                                </button>
                                <button
                                  onClick={() => onDelete(child)}
                                  className="rounded-xl border border-red-900 px-2 py-0.5 text-[11px] font-medium text-red-400 hover:bg-red-500/10"
                                >
                                  Remove
                                </button>
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}

      <div>
        <h2 className="text-xl font-semibold text-zinc-50">Cloud Providers</h2>
        <p className="text-sm text-zinc-500">
          Credentials the discovery pipeline uses to pull live VPCs/VNets/VCNs and subnets into the
          network inventory. Saving one here switches that account from demo data to live discovery —
          no other step needed.
        </p>
      </div>

      {!loading &&
        CLOUD_SECTIONS.map((section) => {
          const rows = cloudByVendor(section.vendor);
          return (
            <div key={section.vendor} className="rounded-xl border border-white/[0.08] bg-surface-2">
              <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-3">
                <div>
                  <h3 className="text-sm font-semibold text-zinc-100">{section.title}</h3>
                  <p className="text-xs text-zinc-500">{section.blurb}</p>
                </div>
                <button
                  onClick={() => openCloudCreate(section.vendor)}
                  className="rounded-xl bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500"
                >
                  Add {section.title}
                </button>
              </div>

              {rows.length === 0 ? (
                <p className="px-4 py-4 text-sm text-zinc-500">None configured yet — using demo data.</p>
              ) : (
                <ul className="divide-y divide-white/[0.06]">
                  {rows.map((row) => (
                    <li key={row.id} className="flex items-center justify-between gap-3 px-4 py-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-zinc-100">{row.name}</span>
                          <CloudStatusBadge row={row} />
                          {!row.is_active && (
                            <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[11px] text-zinc-500">disabled</span>
                          )}
                        </div>
                        <p className="truncate text-xs text-zinc-500">
                          {section.idLabel} {row.account_identifier}
                          {row.region_default && <> &middot; {row.region_default}</>}
                          {row.credential_summary && <> &middot; {row.credential_summary}</>}
                        </p>
                        {row.last_test_message && row.last_test_status === "error" && (
                          <p className="truncate text-xs text-red-500">{row.last_test_message}</p>
                        )}
                      </div>
                      <div className="flex flex-shrink-0 items-center gap-2">
                        <button
                          onClick={() => onCloudTest(row)}
                          disabled={cloudTestingId === row.id}
                          className="rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500 hover:bg-white/[0.04] disabled:opacity-50"
                        >
                          {cloudTestingId === row.id ? "Testing…" : "Test"}
                        </button>
                        <button
                          onClick={() => openCloudEdit(row)}
                          className="rounded-xl border border-white/[0.08] px-2.5 py-1 text-xs font-medium text-zinc-500 hover:bg-white/[0.04]"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => onCloudDelete(row)}
                          className="rounded-xl border border-red-900 px-2.5 py-1 text-xs font-medium text-red-400 hover:bg-red-500/10"
                        >
                          Remove
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}

      {cloudForm && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/70 p-4">
          <form
            onSubmit={onCloudSubmit}
            className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl bg-surface-2 p-6 shadow-xl"
          >
            <h3 className="mb-4 text-base font-semibold text-zinc-50">
              {cloudForm.id ? "Edit" : "Add"} {CLOUD_SECTIONS.find((s) => s.vendor === cloudForm.vendor)?.title}
            </h3>

            <label className="mb-3 block text-sm text-zinc-500">
              Name
              <input
                required
                className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                value={cloudForm.name}
                onChange={(e) => setCloudForm({ ...cloudForm, name: e.target.value })}
                placeholder={`e.g. Prod ${CLOUD_SECTIONS.find((s) => s.vendor === cloudForm.vendor)?.title}`}
              />
            </label>

            <label className="mb-3 block text-sm text-zinc-500">
              {CLOUD_SECTIONS.find((s) => s.vendor === cloudForm.vendor)?.idLabel}
              <input
                required
                disabled={!!cloudForm.id}
                className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100 disabled:bg-white/[0.04] disabled:text-zinc-500"
                value={cloudForm.account_identifier}
                onChange={(e) => setCloudForm({ ...cloudForm, account_identifier: e.target.value })}
                placeholder={CLOUD_SECTIONS.find((s) => s.vendor === cloudForm.vendor)?.idPlaceholder}
              />
            </label>

            <label className="mb-3 block text-sm text-zinc-500">
              Default region (optional)
              <input
                className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                value={cloudForm.region_default}
                onChange={(e) => setCloudForm({ ...cloudForm, region_default: e.target.value })}
                placeholder={cloudForm.vendor === "aws" ? "us-east-1" : cloudForm.vendor === "azure" ? "eastus" : ""}
              />
            </label>

            {cloudForm.vendor === "aws" && (
              <>
                <label className="mb-3 block text-sm text-zinc-500">
                  Auth mode
                  <select
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={cloudForm.auth_mode}
                    onChange={(e) => setCloudForm({ ...cloudForm, auth_mode: e.target.value as "access_key" | "role_arn" })}
                  >
                    <option value="access_key">Access key</option>
                    <option value="role_arn">Assumable IAM role</option>
                  </select>
                </label>
                {cloudForm.auth_mode === "access_key" ? (
                  <>
                    <label className="mb-3 block text-sm text-zinc-500">
                      Access key ID
                      <input
                        className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                        value={cloudForm.access_key_id}
                        onChange={(e) => setCloudForm({ ...cloudForm, access_key_id: e.target.value })}
                      />
                    </label>
                    <label className="mb-3 block text-sm text-zinc-500">
                      Secret access key
                      <input
                        type="password" autoComplete="new-password"
                        className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                        value={cloudForm.secret_access_key}
                        onChange={(e) => setCloudForm({ ...cloudForm, secret_access_key: e.target.value })}
                        placeholder={cloudForm.id ? "Leave blank to keep the current one" : ""}
                      />
                    </label>
                  </>
                ) : (
                  <>
                    <label className="mb-3 block text-sm text-zinc-500">
                      Role ARN
                      <input
                        className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                        value={cloudForm.role_arn}
                        onChange={(e) => setCloudForm({ ...cloudForm, role_arn: e.target.value })}
                        placeholder="arn:aws:iam::111111111111:role/netsphere-discovery"
                      />
                    </label>
                    <label className="mb-3 block text-sm text-zinc-500">
                      External ID (optional)
                      <input
                        className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                        value={cloudForm.external_id}
                        onChange={(e) => setCloudForm({ ...cloudForm, external_id: e.target.value })}
                      />
                    </label>
                  </>
                )}
              </>
            )}

            {cloudForm.vendor === "azure" && (
              <>
                <label className="mb-3 block text-sm text-zinc-500">
                  Tenant ID
                  <input
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={cloudForm.tenant_id}
                    onChange={(e) => setCloudForm({ ...cloudForm, tenant_id: e.target.value })}
                  />
                </label>
                <label className="mb-3 block text-sm text-zinc-500">
                  Client (application) ID
                  <input
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={cloudForm.client_id}
                    onChange={(e) => setCloudForm({ ...cloudForm, client_id: e.target.value })}
                  />
                </label>
                <label className="mb-3 block text-sm text-zinc-500">
                  Client secret
                  <input
                    type="password" autoComplete="new-password"
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={cloudForm.client_secret}
                    onChange={(e) => setCloudForm({ ...cloudForm, client_secret: e.target.value })}
                    placeholder={cloudForm.id ? "Leave blank to keep the current one" : ""}
                  />
                </label>
              </>
            )}

            {cloudForm.vendor === "gcp" && (
              <label className="mb-3 block text-sm text-zinc-500">
                Service account JSON key
                <textarea
                  className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 font-mono text-xs text-zinc-100"
                  rows={6}
                  value={cloudForm.service_account_json}
                  onChange={(e) => setCloudForm({ ...cloudForm, service_account_json: e.target.value })}
                  placeholder={cloudForm.id ? "Leave blank to keep the current one" : '{"type": "service_account", ...}'}
                />
              </label>
            )}

            {cloudForm.vendor === "oci" && (
              <>
                <label className="mb-3 block text-sm text-zinc-500">
                  User OCID
                  <input
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={cloudForm.user_ocid}
                    onChange={(e) => setCloudForm({ ...cloudForm, user_ocid: e.target.value })}
                  />
                </label>
                <label className="mb-3 block text-sm text-zinc-500">
                  Tenancy OCID
                  <input
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={cloudForm.tenancy_ocid}
                    onChange={(e) => setCloudForm({ ...cloudForm, tenancy_ocid: e.target.value })}
                  />
                </label>
                <label className="mb-3 block text-sm text-zinc-500">
                  Fingerprint
                  <input
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={cloudForm.fingerprint}
                    onChange={(e) => setCloudForm({ ...cloudForm, fingerprint: e.target.value })}
                    placeholder="aa:bb:cc:..."
                  />
                </label>
                <label className="mb-3 block text-sm text-zinc-500">
                  Private key (PEM)
                  <textarea
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 font-mono text-xs text-zinc-100"
                    rows={5}
                    value={cloudForm.private_key_pem}
                    onChange={(e) => setCloudForm({ ...cloudForm, private_key_pem: e.target.value })}
                    placeholder={cloudForm.id ? "Leave blank to keep the current one" : "-----BEGIN PRIVATE KEY-----"}
                  />
                </label>
                <label className="mb-3 block text-sm text-zinc-500">
                  Region
                  <input
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={cloudForm.region}
                    onChange={(e) => setCloudForm({ ...cloudForm, region: e.target.value })}
                    placeholder="us-ashburn-1"
                  />
                </label>
              </>
            )}

            <label className="mb-4 block text-sm text-zinc-500">
              Notes
              <textarea
                className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                rows={2}
                value={cloudForm.notes}
                onChange={(e) => setCloudForm({ ...cloudForm, notes: e.target.value })}
              />
            </label>

            {cloudFormError && <p className="mb-3 text-sm text-red-400">{cloudFormError}</p>}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCloudForm(null)}
                className="rounded-xl border border-white/[0.08] px-4 py-2 text-sm font-medium text-zinc-500 hover:bg-white/[0.04]"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={cloudSaving}
                className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
              >
                {cloudSaving ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        </div>
      )}

      {form && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/70 p-4">
          <form
            onSubmit={onSubmit}
            className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl bg-surface-2 p-6 shadow-xl"
          >
            <h3 className="mb-4 text-base font-semibold text-zinc-50">
              {form.id ? "Edit" : "Add"} {form.vendor === "ngfw" ? "NGFW" : form.vendor}
            </h3>

            <label className="mb-3 block text-sm text-zinc-500">
              Name
              <input
                required
                className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={form.vendor === "ngfw" ? "e.g. NGFW-EastUS-01" : "e.g. Prod Panorama"}
              />
            </label>

            {form.vendor === "ngfw" ? (
              <>
                <label className="mb-3 block text-sm text-zinc-500">
                  Device group (on Panorama)
                  <input
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={form.device_group}
                    onChange={(e) => setForm({ ...form, device_group: e.target.value })}
                    placeholder="DG-EastUS-Prod"
                  />
                </label>
                <label className="mb-3 block text-sm text-zinc-500">
                  Serial (optional)
                  <input
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={form.serial}
                    onChange={(e) => setForm({ ...form, serial: e.target.value })}
                  />
                </label>
              </>
            ) : (
              <>
                <div className="mb-3 flex gap-3">
                  <label className="flex-1 text-sm text-zinc-500">
                    Host / IP
                    <input
                      required={!form.id}
                      className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                      value={form.host}
                      onChange={(e) => setForm({ ...form, host: e.target.value })}
                      placeholder="panorama.corp.local"
                    />
                  </label>
                  <label className="w-24 text-sm text-zinc-500">
                    Port
                    <input
                      type="number"
                      className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                      value={form.port}
                      onChange={(e) => setForm({ ...form, port: e.target.value })}
                    />
                  </label>
                </div>
                <label className="mb-3 flex items-center gap-2 text-sm text-zinc-500">
                  <input
                    type="checkbox"
                    checked={form.verify_tls}
                    onChange={(e) => setForm({ ...form, verify_tls: e.target.checked })}
                  />
                  Verify TLS certificate
                </label>
                <label className="mb-3 block text-sm text-zinc-500">
                  Auth type
                  <select
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={form.auth_type}
                    onChange={(e) => setForm({ ...form, auth_type: e.target.value as FormState["auth_type"] })}
                  >
                    <option value="api_key">API key</option>
                    <option value="username_password">Username + password</option>
                  </select>
                </label>
                {form.auth_type === "username_password" && (
                  <label className="mb-3 block text-sm text-zinc-500">
                    Username
                    <input
                      className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                      value={form.username}
                      onChange={(e) => setForm({ ...form, username: e.target.value })}
                    />
                  </label>
                )}
                <label className="mb-3 block text-sm text-zinc-500">
                  {form.auth_type === "api_key" ? "API key" : "Password"}
                  <input
                    type="password"
                    autoComplete="new-password"
                    className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                    value={form.secret}
                    onChange={(e) => setForm({ ...form, secret: e.target.value })}
                    placeholder={form.id ? "Leave blank to keep the current one" : ""}
                  />
                </label>
              </>
            )}

            <label className="mb-4 block text-sm text-zinc-500">
              Notes
              <textarea
                className="mt-1 w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
                rows={2}
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
              />
            </label>

            {formError && <p className="mb-3 text-sm text-red-400">{formError}</p>}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setForm(null)}
                className="rounded-xl border border-white/[0.08] px-4 py-2 text-sm font-medium text-zinc-500 hover:bg-white/[0.04]"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
