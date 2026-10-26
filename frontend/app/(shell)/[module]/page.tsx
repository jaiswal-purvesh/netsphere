const PHASE_BY_SLUG: Record<string, string> = {
  "network-inventory": "Phase 2 (devices/interfaces beyond what IPAM already covers)",
  topology: "Phase 4",
  automation: "Phase 7 — converges with fwauto's plan/PoA/approval/execute pipeline",
  changes: "Phase 7",
  compliance: "Phase 6",
  monitoring: "Phase 8",
  incidents: "Phase 8",
  reports: "Phase 10",
  "ai-assistant": "Phase 9",
  administration: "Phase 10 (SSO/OIDC, resource-scoped RBAC)",
};

export default function ModulePlaceholder({ params }: { params: { module: string } }) {
  const phase = PHASE_BY_SLUG[params.module] ?? "a future phase";
  const title = params.module
    .split("-")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold text-zinc-50">{title}</h1>
      <div className="rounded-xl border border-dashed border-white/[0.08] bg-surface-2 p-8 text-sm text-zinc-500">
        <p className="font-medium text-zinc-600">Not implemented yet.</p>
        <p className="mt-1">
          This module is designed in <code className="rounded bg-white/[0.06] px-1">docs/ARCHITECTURE.md</code> and{" "}
          <code className="rounded bg-white/[0.06] px-1">docs/ROADMAP.md</code>, scheduled for {phase}. Nothing here is
          mocked or faked in the meantime — this page exists only so the full navigation is visible up front.
        </p>
      </div>
    </div>
  );
}
