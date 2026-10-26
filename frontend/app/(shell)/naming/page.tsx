"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";

// Naming — one standard for every network component, cloud and on-prem.
// The convention itself lives in the backend (app/services/naming.py); this
// page only collects choices and shows what the server says, so the rule is
// never duplicated client-side and can't drift from what the audit enforces.
// Names are generated and checked, not reserved — nothing here writes to the
// inventory.

type Component = {
  id: string;
  label: string;
  scope: "cloud" | "onprem";
  pattern: string;
  help: string;
  needs_role: boolean;
  roles: string[];
  type_codes: Record<string, string>;
};

type Spec = {
  org: string;
  environments: { code: string; label: string }[];
  regions: Record<string, { value: string; code: string; label: string }[]>;
  providers: { id: string; label: string; max_len: number; note: string }[];
  device_kinds: { id: string; code: string }[];
  sites: string[];
  components: Component[];
  rules: string[];
};

type GenerateResult = {
  name: string | null;
  pattern: string;
  parts: Record<string, string>;
  issues: string[];
  unique: boolean | null;
  collisions: { name: string; where: string }[];
  seq: number | null;
  alternatives: string[];
};

type ValidateResult = { compliant: boolean; issues: string[]; parts: Record<string, string>; pattern: string };

type AuditItem = {
  name: string;
  provider: string | null;
  context: string;
  compliant: boolean;
  issues: string[];
  suggestion: string | null;
};
type AuditSection = {
  component: string;
  label: string;
  scope: "cloud" | "onprem";
  pattern: string;
  total: number;
  compliant: number;
  items: AuditItem[];
};
type Audit = { total: number; compliant: number; non_compliant: number; sections: AuditSection[] };

const inputCls =
  "w-full rounded-lg border border-white/[0.1] bg-surface-1 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-indigo-500/60 focus:outline-none";
const labelCls = "mb-1 block text-xs font-medium text-zinc-400";

function StatCard({ label, value, tone }: { label: string; value: number | string; tone?: "good" | "bad" }) {
  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4 shadow-card">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p
        className={`mt-1.5 font-mono text-2xl font-semibold tracking-tight ${
          tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-amber-400" : "text-zinc-50"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function Badge({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
        ok
          ? "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30"
          : "bg-amber-500/10 text-amber-400 ring-amber-500/30"
      }`}
    >
      {children}
    </span>
  );
}

/** A name rendered segment by segment, so the structure of the convention is
 * visible, not just a string. */
function SegmentedName({ name, parts }: { name: string; parts: Record<string, string> }) {
  const tokens = Object.entries(parts);
  if (!tokens.length) return <span className="font-mono text-zinc-100">{name}</span>;
  return (
    <div className="flex flex-wrap items-end gap-x-1 gap-y-2 font-mono text-lg text-zinc-50">
      {tokens.map(([token, value], i) => (
        <span key={token} className="flex items-end gap-1">
          <span className="flex flex-col items-center">
            <span>{value}</span>
            <span className="mt-0.5 text-[10px] font-sans uppercase tracking-wide text-zinc-500">{token}</span>
          </span>
          {i < tokens.length - 1 && <span className="pb-4 text-zinc-600">-</span>}
        </span>
      ))}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard
          .writeText(text)
          .then(() => {
            setDone(true);
            setTimeout(() => setDone(false), 1500);
          })
          .catch(() => undefined);
      }}
      className="rounded-lg border border-white/[0.1] px-2.5 py-1 text-xs text-zinc-300 hover:bg-white/[0.06]"
    >
      {done ? "Copied" : "Copy"}
    </button>
  );
}

// ---------------------------------------------------------------- builder

function BuilderTab({ spec }: { spec: Spec }) {
  const [componentId, setComponentId] = useState("network");
  const comp = spec.components.find((c) => c.id === componentId)!;
  const [provider, setProvider] = useState("aws");
  const [env, setEnv] = useState("prd");
  const [region, setRegion] = useState("");
  const [site, setSite] = useState("");
  const [app, setApp] = useState("");
  const [role, setRole] = useState("");
  const [kind, setKind] = useState("router");
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const regions = spec.regions[provider] ?? [];

  // Regenerate whenever an input changes; the server is the only place the
  // rule lives, so there is no client-side string building to get wrong.
  useEffect(() => {
    if (comp.scope === "cloud" && !region && regions.length) setRegion(regions[0].value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, componentId]);

  useEffect(() => {
    if (comp.needs_role && !comp.roles.includes(role)) setRole(comp.roles[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentId]);

  useEffect(() => {
    const handle = setTimeout(() => {
      setError(null);
      api
        .post<GenerateResult>("/naming/generate", {
          component: componentId,
          provider: comp.scope === "cloud" ? provider : undefined,
          env: comp.scope === "cloud" ? env : undefined,
          region: comp.scope === "cloud" ? region : undefined,
          site: comp.scope === "onprem" ? site : undefined,
          app: app || undefined,
          role: comp.needs_role ? role : undefined,
          kind: componentId === "device" ? kind : undefined,
        })
        .then(setResult)
        .catch((e) => setError(e instanceof ApiError ? String(e.detail) : "failed to generate a name"));
    }, 250);
    return () => clearTimeout(handle);
  }, [componentId, provider, env, region, site, app, role, kind, comp.scope, comp.needs_role]);

  const cloud = useMemo(() => spec.components.filter((c) => c.scope === "cloud"), [spec]);
  const onprem = useMemo(() => spec.components.filter((c) => c.scope === "onprem"), [spec]);
  const needsApp = comp.pattern.includes("{app}");

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
      <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-5 shadow-card">
        <h2 className="mb-4 text-sm font-semibold text-zinc-100">What are you naming?</h2>

        <label className={labelCls}>Component</label>
        <select value={componentId} onChange={(e) => setComponentId(e.target.value)} className={inputCls}>
          <optgroup label="Cloud">
            {cloud.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </optgroup>
          <optgroup label="On-prem">
            {onprem.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </optgroup>
        </select>
        {comp.help && <p className="mt-1.5 text-xs text-zinc-500">{comp.help}</p>}
        <p className="mt-1 font-mono text-xs text-zinc-500">{comp.pattern}</p>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {comp.scope === "cloud" && (
            <>
              <div>
                <label className={labelCls}>Cloud provider</label>
                <select
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value);
                    setRegion("");
                  }}
                  className={inputCls}
                >
                  {spec.providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>Environment</label>
                <select value={env} onChange={(e) => setEnv(e.target.value)} className={inputCls}>
                  {spec.environments.map((e) => (
                    <option key={e.code} value={e.code}>
                      {e.label} ({e.code})
                    </option>
                  ))}
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className={labelCls}>Region</label>
                <select value={region} onChange={(e) => setRegion(e.target.value)} className={inputCls}>
                  {regions.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label} — {r.code}
                    </option>
                  ))}
                </select>
              </div>
            </>
          )}

          {comp.scope === "onprem" && (
            <div>
              <label className={labelCls}>Site</label>
              <input
                list="naming-sites"
                value={site}
                onChange={(e) => setSite(e.target.value)}
                placeholder="dc1"
                className={inputCls}
              />
              <datalist id="naming-sites">
                {spec.sites.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </div>
          )}

          {comp.needs_role && (
            <div>
              <label className={labelCls}>Role</label>
              <select value={role} onChange={(e) => setRole(e.target.value)} className={inputCls}>
                {comp.roles.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
          )}

          {componentId === "device" && (
            <div>
              <label className={labelCls}>Device kind</label>
              <select value={kind} onChange={(e) => setKind(e.target.value)} className={inputCls}>
                {spec.device_kinds.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.id.replace("_", " ")} ({k.code})
                  </option>
                ))}
              </select>
            </div>
          )}

          {needsApp && (
            <div className="sm:col-span-2">
              <label className={labelCls}>
                {comp.scope === "onprem" && componentId !== "device" ? "Segment / far end" : "Application"}
              </label>
              <input
                value={app}
                onChange={(e) => setApp(e.target.value)}
                placeholder={comp.scope === "cloud" ? "payments  or  payments-web" : "payments"}
                className={inputCls}
              />
              <p className="mt-1 text-xs text-zinc-500">A tier can follow the app, joined with a hyphen.</p>
            </div>
          )}
        </div>
      </div>

      <div className="space-y-4">
        <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-5 shadow-card">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-100">Generated name</h2>
            {result?.name && !result.issues.length && <Badge ok>Compliant · unique</Badge>}
            {result?.name && result.issues.length > 0 && <Badge ok={false}>Needs attention</Badge>}
          </div>

          {error && <p className="text-sm text-red-400">{error}</p>}

          {result?.name ? (
            <>
              <SegmentedName name={result.name} parts={result.parts} />
              <div className="mt-4 flex items-center gap-3">
                <code className="rounded-lg bg-surface-1 px-3 py-1.5 font-mono text-sm text-indigo-300">{result.name}</code>
                <CopyButton text={result.name} />
              </div>
            </>
          ) : (
            <p className="text-sm text-zinc-500">Fill in the fields to build a name.</p>
          )}

          {result && result.issues.length > 0 && (
            <ul className="mt-4 space-y-1 text-sm text-amber-400">
              {result.issues.map((i) => (
                <li key={i}>• {i}</li>
              ))}
            </ul>
          )}

          {result?.name && result.unique && result.seq && (
            <p className="mt-4 text-xs text-zinc-500">
              Sequence {String(result.seq).padStart(2, "0")} is the next free number in the live inventory.
            </p>
          )}
          {result && result.alternatives.length > 0 && (
            <div className="mt-3">
              <p className="text-xs text-zinc-500">If you need more than one:</p>
              <div className="mt-1 flex flex-wrap gap-2">
                {result.alternatives.map((a) => (
                  <code key={a} className="rounded-md bg-surface-1 px-2 py-1 font-mono text-xs text-zinc-300">
                    {a}
                  </code>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-5 shadow-card">
          <h2 className="mb-2 text-sm font-semibold text-zinc-100">The rules</h2>
          <ul className="space-y-1 text-xs text-zinc-400">
            {spec.rules.map((r) => (
              <li key={r}>• {r}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// -------------------------------------------------------------- validator

function ValidatorTab({ spec }: { spec: Spec }) {
  const [componentId, setComponentId] = useState("network");
  const [provider, setProvider] = useState("aws");
  const [name, setName] = useState("");
  const [result, setResult] = useState<ValidateResult | null>(null);
  const comp = spec.components.find((c) => c.id === componentId)!;

  useEffect(() => {
    if (!name.trim()) {
      setResult(null);
      return;
    }
    const handle = setTimeout(() => {
      api
        .post<ValidateResult>("/naming/validate", {
          name,
          component: componentId,
          provider: comp.scope === "cloud" ? provider : undefined,
        })
        .then(setResult)
        .catch(() => setResult(null));
    }, 250);
    return () => clearTimeout(handle);
  }, [name, componentId, provider, comp.scope]);

  return (
    <div className="max-w-3xl rounded-xl border border-white/[0.08] bg-surface-2 p-5 shadow-card">
      <p className="mb-4 text-sm text-zinc-400">
        Paste a name — yours, or one from a request — and check it against the standard, including the chosen
        cloud&apos;s own limits.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelCls}>Component</label>
          <select value={componentId} onChange={(e) => setComponentId(e.target.value)} className={inputCls}>
            {spec.components.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
        {comp.scope === "cloud" && (
          <div>
            <label className={labelCls}>Cloud provider</label>
            <select value={provider} onChange={(e) => setProvider(e.target.value)} className={inputCls}>
              {spec.providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="sm:col-span-2">
          <label className={labelCls}>Name to check</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={comp.pattern} className={`${inputCls} font-mono`} />
        </div>
      </div>

      {result && (
        <div className="mt-5">
          <Badge ok={result.compliant}>{result.compliant ? "Compliant" : "Not compliant"}</Badge>
          {result.compliant && <div className="mt-3"><SegmentedName name={name} parts={result.parts} /></div>}
          {result.issues.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm text-amber-400">
              {result.issues.map((i) => (
                <li key={i}>• {i}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ audit

function AuditTab() {
  const [audit, setAudit] = useState<Audit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [onlyBad, setOnlyBad] = useState(true);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  useEffect(() => {
    api
      .get<Audit>("/naming/audit")
      .then(setAudit)
      .catch((e) => setError(e instanceof ApiError ? String(e.detail) : "failed to load the audit"));
  }, []);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (!audit) return <p className="text-sm text-zinc-500">Scoring the inventory…</p>;

  const pct = audit.total ? Math.round((audit.compliant / audit.total) * 100) : 100;

  return (
    <div>
      <div className="mb-5 grid gap-4 sm:grid-cols-4">
        <StatCard label="Named objects" value={audit.total} />
        <StatCard label="Compliant" value={audit.compliant} tone="good" />
        <StatCard label="Non-compliant" value={audit.non_compliant} tone={audit.non_compliant ? "bad" : "good"} />
        <StatCard label="Compliance" value={`${pct}%`} />
      </div>

      <p className="mb-4 text-xs text-zinc-500">
        Suggested names are a starting point built from what the old name reveals (environment, region, type). Check
        the application segment before you rename anything — renaming a live cloud object usually means recreating it.
      </p>

      <label className="mb-4 flex items-center gap-2 text-sm text-zinc-300">
        <input type="checkbox" checked={onlyBad} onChange={(e) => setOnlyBad(e.target.checked)} />
        Show only non-compliant names
      </label>

      <div className="space-y-3">
        {audit.sections
          .filter((s) => s.total > 0)
          .map((s) => {
            const rows = onlyBad ? s.items.filter((i) => !i.compliant) : s.items;
            const isOpen = open[s.component] ?? true;
            return (
              <div key={s.component} className="rounded-xl border border-white/[0.08] bg-surface-2 shadow-card">
                <button
                  onClick={() => setOpen({ ...open, [s.component]: !isOpen })}
                  className="flex w-full items-center justify-between px-4 py-3 text-left"
                >
                  <span>
                    <span className="text-sm font-medium text-zinc-100">{s.label}</span>
                    <span className="ml-3 font-mono text-xs text-zinc-500">{s.pattern}</span>
                  </span>
                  <Badge ok={s.compliant === s.total}>
                    {s.compliant} / {s.total} compliant
                  </Badge>
                </button>
                {isOpen && rows.length > 0 && (
                  <div className="overflow-x-auto border-t border-white/[0.06] px-4 py-2">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="text-zinc-500">
                          <th className="py-1.5 pr-4 font-medium">Current name</th>
                          <th className="py-1.5 pr-4 font-medium">Where</th>
                          <th className="py-1.5 pr-4 font-medium">Why not compliant</th>
                          <th className="py-1.5 font-medium">Suggested</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((i) => (
                          <tr key={`${s.component}-${i.name}`} className="border-t border-white/[0.04] align-top">
                            <td className="py-1.5 pr-4 font-mono text-zinc-200">{i.name}</td>
                            <td className="py-1.5 pr-4 text-zinc-500">{i.context || "—"}</td>
                            <td className="py-1.5 pr-4 text-amber-400/90">{i.issues[i.issues.length - 1] ?? "—"}</td>
                            <td className="py-1.5">
                              {i.suggestion ? (
                                <span className="flex items-center gap-2">
                                  <code className="font-mono text-indigo-300">{i.suggestion}</code>
                                  <CopyButton text={i.suggestion} />
                                </span>
                              ) : (
                                <span className="text-zinc-600">—</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {isOpen && rows.length === 0 && (
                  <p className="border-t border-white/[0.06] px-4 py-3 text-xs text-emerald-400">All names comply.</p>
                )}
              </div>
            );
          })}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- page

export default function NamingPage() {
  const [tab, setTab] = useState<"builder" | "validator" | "audit">("builder");
  const [spec, setSpec] = useState<Spec | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Spec>("/naming/spec")
      .then(setSpec)
      .catch((e) => setError(e instanceof ApiError ? String(e.detail) : "failed to load the naming standard"));
  }, []);

  const tabs: { id: "builder" | "validator" | "audit"; label: string }[] = [
    { id: "builder", label: "Name builder" },
    { id: "validator", label: "Check a name" },
    { id: "audit", label: "Inventory audit" },
  ];

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold text-zinc-50">Naming</h1>
      <p className="mb-5 max-w-3xl text-sm text-zinc-400">
        One naming standard for every network component, cloud and on-prem. Build a compliant, unique name before you
        create anything, check a name someone sent you, or audit what already exists.
      </p>

      <div className="mb-6 flex gap-2 border-b border-white/[0.08]">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              tab === t.id
                ? "border-indigo-400 text-zinc-50"
                : "border-transparent text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
      {!spec && !error && <p className="text-sm text-zinc-500">Loading…</p>}
      {spec && tab === "builder" && <BuilderTab spec={spec} />}
      {spec && tab === "validator" && <ValidatorTab spec={spec} />}
      {spec && tab === "audit" && <AuditTab />}
    </div>
  );
}
