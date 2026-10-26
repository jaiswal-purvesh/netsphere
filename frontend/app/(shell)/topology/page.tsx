"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import * as d3force from "d3-force";
import { select } from "d3-selection";
import { drag as d3drag } from "d3-drag";
import { zoom as d3zoom, zoomIdentity, type ZoomTransform } from "d3-zoom";
import "d3-transition"; // side-effect: adds Selection.prototype.transition, used below
import { api, ApiError } from "@/lib/api";

type NodeType = "organization" | "business_unit" | "environment" | "cloud_account" | "network" | "subnet" | "device" | "firewall";

type TopoNode = {
  id: string;
  type: NodeType;
  label: string;
  parent_id: string | null;
  meta: Record<string, unknown>;
};

type TopoEdge = {
  from: string;
  to: string;
  kind: "contains" | "protected_by" | "attached_via";
  label?: string;
};

type Topology = { nodes: TopoNode[]; edges: TopoEdge[] };
type EnvOption = { id: string; name: string };

type SimNode = TopoNode & d3force.SimulationNodeDatum;
type SimLink = { source: string | SimNode; target: string | SimNode; kind: TopoEdge["kind"]; label?: string };

const TYPE_LABEL: Record<NodeType, string> = {
  organization: "Organization",
  business_unit: "Business Unit",
  environment: "Environment",
  cloud_account: "Cloud Account",
  network: "Network",
  subnet: "Subnet",
  device: "Device",
  firewall: "Firewall",
};

// Fill colors mirror the Tailwind palette used elsewhere in the app
// (indigo/sky/emerald/teal/amber/rose) so this reads as the same design
// system, just rendered to an SVG canvas instead of Tailwind classes.
const TYPE_COLOR: Record<NodeType, string> = {
  organization: "#94a3b8",
  business_unit: "#94a3b8",
  environment: "#6366f1",
  cloud_account: "#0ea5e9",
  network: "#10b981",
  subnet: "#2dd4bf",
  device: "#f59e0b",
  firewall: "#f43f5e",
};

const TYPE_RADIUS: Record<NodeType, number> = {
  organization: 11,
  business_unit: 10,
  environment: 10,
  cloud_account: 8,
  network: 7,
  subnet: 5,
  device: 7,
  firewall: 8,
};

const EDGE_STYLE: Record<TopoEdge["kind"], { stroke: string; width: number; dash?: string }> = {
  contains: { stroke: "#334155", width: 1.2 },
  protected_by: { stroke: "#fb7185", width: 1.5, dash: "5,3" },
  attached_via: { stroke: "#f59e0b", width: 1.2, dash: "2,3" },
};

function Legend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
      {(Object.keys(TYPE_LABEL) as NodeType[]).map((t) => (
        <span key={t} className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: TYPE_COLOR[t] }} />
          {TYPE_LABEL[t]}
        </span>
      ))}
      <span className="ml-2 flex items-center gap-1 text-zinc-500">
        <span className="inline-block h-0 w-4 border-t border-dashed" style={{ borderColor: EDGE_STYLE.protected_by.stroke }} /> protected by
      </span>
      <span className="flex items-center gap-1 text-zinc-500">
        <span className="inline-block h-0 w-4 border-t border-dotted" style={{ borderColor: EDGE_STYLE.attached_via.stroke }} /> attached via
      </span>
    </div>
  );
}

function DetailPanel({ node }: { node: TopoNode }) {
  const entries = Object.entries(node.meta).filter(([, v]) => v !== null && v !== undefined && v !== "");
  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: TYPE_COLOR[node.type] }} />
        <h3 className="text-sm font-semibold text-zinc-50">{node.label}</h3>
      </div>
      <p className="mb-3 text-xs uppercase tracking-wide text-zinc-500">{TYPE_LABEL[node.type]}</p>
      {entries.length > 0 ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          {entries.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-zinc-500">{k.replace(/_/g, " ")}</dt>
              <dd className="truncate text-zinc-300">{String(v)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-sm text-zinc-500">No additional attributes.</p>
      )}
    </div>
  );
}

const WIDTH = 900;
const HEIGHT = 620;

export default function TopologyPage() {
  const [envs, setEnvs] = useState<EnvOption[]>([]);
  const [envId, setEnvId] = useState<string>("");
  const [topology, setTopology] = useState<Topology | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<TopoNode | null>(null);
  const [q, setQ] = useState("");

  const svgRef = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<d3force.Simulation<SimNode, SimLink> | null>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const linksRef = useRef<SimLink[]>([]);
  const [tick, setTick] = useState(0); // bumped on every simulation tick to force a re-render
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);

  useEffect(() => {
    api
      .get<EnvOption[]>("/orgs/environments")
      .then(setEnvs)
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setSelected(null);
    const path = envId ? `/topology?environment_id=${envId}` : "/topology";
    api
      .get<Topology>(path)
      .then(setTopology)
      .catch((e) => setError(e instanceof ApiError ? String(e.detail) : "failed to load topology"))
      .finally(() => setLoading(false));
  }, [envId]);

  // Build and run the force simulation whenever a fresh topology arrives.
  // Ticked synchronously to a settled layout (no live physics after that —
  // dragging a node just repositions it, which keeps the graph legible
  // instead of jittering every time someone touches it).
  useEffect(() => {
    if (!topology) return;
    simRef.current?.stop();

    const nodes: SimNode[] = topology.nodes.map((n) => ({ ...n }));
    const nodeIds = new Set(nodes.map((n) => n.id));
    const links: SimLink[] = topology.edges
      .filter((e) => nodeIds.has(e.from) && nodeIds.has(e.to))
      .map((e) => ({ source: e.from, target: e.to, kind: e.kind, label: e.label }));

    const sim = d3force
      .forceSimulation(nodes)
      .force(
        "link",
        d3force
          .forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance((l) => (l.kind === "contains" ? 55 : l.kind === "protected_by" ? 100 : 70))
          .strength((l) => (l.kind === "contains" ? 0.8 : 0.25)),
      )
      .force("charge", d3force.forceManyBody().strength(-140))
      .force("center", d3force.forceCenter(WIDTH / 2, HEIGHT / 2))
      .force(
        "collide",
        d3force.forceCollide<SimNode>().radius((d) => TYPE_RADIUS[d.type] + 6),
      )
      .stop();

    for (let i = 0; i < 250; i++) sim.tick();

    nodesRef.current = nodes;
    linksRef.current = links;
    simRef.current = sim;
    setTick((t) => t + 1);
  }, [topology]);

  // Pan/zoom on the SVG background.
  useEffect(() => {
    if (!svgRef.current) return;
    const svgSel = select(svgRef.current);
    const behavior = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.25, 3])
      .on("zoom", (event) => setTransform(event.transform));
    svgSel.call(behavior);
    return () => {
      svgSel.on(".zoom", null);
    };
  }, [topology]);

  // Drag-to-reposition on each node group.
  const applyDrag = useCallback((el: SVGGElement | null, node: SimNode) => {
    if (!el) return;
    select(el).call(
      d3drag<SVGGElement, unknown>()
        .on("start", () => {
          node.fx = node.x;
          node.fy = node.y;
        })
        .on("drag", (event) => {
          node.fx = event.x;
          node.fy = event.y;
          node.x = event.x;
          node.y = event.y;
          setTick((t) => t + 1);
        }),
    );
  }, []);

  const nodeById = useMemo(() => new Map(nodesRef.current.map((n) => [n.id, n])), [tick]);

  const matches = useMemo(() => {
    if (!q.trim()) return new Set<string>();
    const needle = q.toLowerCase();
    return new Set(nodesRef.current.filter((n) => n.label.toLowerCase().includes(needle)).map((n) => n.id));
  }, [q, tick]);

  function focusNode(n: SimNode) {
    setSelected(n);
    if (n.x === undefined || n.y === undefined || !svgRef.current) return;
    const svgSel = select(svgRef.current);
    const behavior = d3zoom<SVGSVGElement, unknown>().scaleExtent([0.25, 3]);
    const t = zoomIdentity.translate(WIDTH / 2 - n.x * 1.4, HEIGHT / 2 - n.y * 1.4).scale(1.4);
    svgSel.transition().duration(400).call(behavior.transform, t);
  }

  function zoomBy(factor: number) {
    if (!svgRef.current) return;
    const svgSel = select(svgRef.current);
    const behavior = d3zoom<SVGSVGElement, unknown>().scaleExtent([0.25, 3]);
    svgSel.transition().duration(200).call(behavior.scaleBy, factor);
  }

  function resetView() {
    if (!svgRef.current) return;
    const svgSel = select(svgRef.current);
    const behavior = d3zoom<SVGSVGElement, unknown>().scaleExtent([0.25, 3]);
    svgSel.transition().duration(300).call(behavior.transform, zoomIdentity);
  }

  const counts = useMemo(() => {
    if (!topology) return null;
    const c: Record<string, number> = {};
    for (const n of topology.nodes) c[n.type] = (c[n.type] ?? 0) + 1;
    return c;
  }, [topology]);

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold text-zinc-50">Topology</h1>
      <p className="mb-6 text-sm text-zinc-500">
        A live network map — every node and relationship drawn from the org hierarchy, IPAM, and device inventory, laid
        out as a force-directed graph rather than a separately maintained diagram.
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-white/[0.08] bg-surface-2 p-4">
        <select
          className="rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
          value={envId}
          onChange={(e) => setEnvId(e.target.value)}
        >
          <option value="">All environments</option>
          {envs.map((e) => (
            <option key={e.id} value={e.id}>
              {e.name}
            </option>
          ))}
        </select>
        <input
          className="min-w-[220px] flex-1 rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
          placeholder="Search nodes by name"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {counts && (
          <div className="ml-auto flex flex-wrap gap-3 text-xs text-zinc-500">
            {Object.entries(counts).map(([type, n]) => (
              <span key={type} className="flex items-center gap-1">
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: TYPE_COLOR[type as NodeType] }} />
                {n} {TYPE_LABEL[type as NodeType]}
                {n !== 1 ? "s" : ""}
              </span>
            ))}
          </div>
        )}
      </div>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}
      {loading && <p className="mb-4 text-sm text-zinc-500">Loading topology…</p>}

      {q.trim() && matches.size > 0 && (
        <div className="mb-4 flex flex-wrap gap-2 rounded-xl border border-white/[0.08] bg-surface-2 p-3">
          {[...matches].map((id) => {
            const n = nodeById.get(id);
            if (!n) return null;
            return (
              <button
                key={id}
                className="rounded-full border border-indigo-800 bg-indigo-500/10 px-3 py-1 text-xs text-indigo-400 hover:bg-indigo-500/20"
                onClick={() => focusNode(n)}
              >
                {n.label}
              </button>
            );
          })}
        </div>
      )}
      {q.trim() && matches.size === 0 && <p className="mb-4 text-sm text-zinc-500">No nodes match &ldquo;{q}&rdquo;.</p>}

      {topology && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="lg:col-span-3">
            <div className="relative rounded-xl border border-white/[0.08] bg-surface-2">
              <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-2">
                <Legend />
                <div className="flex gap-1">
                  <button onClick={() => zoomBy(1.3)} className="rounded border border-white/[0.08] px-2 py-1 text-xs text-zinc-500 hover:bg-white/[0.06]">
                    +
                  </button>
                  <button onClick={() => zoomBy(1 / 1.3)} className="rounded border border-white/[0.08] px-2 py-1 text-xs text-zinc-500 hover:bg-white/[0.06]">
                    −
                  </button>
                  <button onClick={resetView} className="rounded border border-white/[0.08] px-2 py-1 text-xs text-zinc-500 hover:bg-white/[0.06]">
                    Reset
                  </button>
                </div>
              </div>
              <svg
                ref={svgRef}
                width="100%"
                viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                className="cursor-grab rounded-b-xl bg-surface-1 active:cursor-grabbing"
              >
                <g transform={transform.toString()}>
                  {linksRef.current.map((l, i) => {
                    const s = typeof l.source === "string" ? nodeById.get(l.source) : (l.source as SimNode);
                    const t = typeof l.target === "string" ? nodeById.get(l.target) : (l.target as SimNode);
                    if (!s || !t || s.x === undefined || t.x === undefined) return null;
                    const style = EDGE_STYLE[l.kind];
                    return (
                      <line
                        key={i}
                        x1={s.x}
                        y1={s.y}
                        x2={t.x}
                        y2={t.y}
                        stroke={style.stroke}
                        strokeWidth={style.width}
                        strokeDasharray={style.dash}
                      />
                    );
                  })}
                  {nodesRef.current.map((n) => {
                    if (n.x === undefined || n.y === undefined) return null;
                    const isSelected = selected?.id === n.id;
                    const isMatch = matches.has(n.id);
                    const r = TYPE_RADIUS[n.type];
                    return (
                      <g
                        key={n.id}
                        ref={(el) => applyDrag(el, n)}
                        transform={`translate(${n.x},${n.y})`}
                        onClick={() => setSelected(n)}
                        className="cursor-pointer"
                      >
                        {(isSelected || isMatch) && (
                          <circle r={r + 4} fill="none" stroke={isSelected ? "#818cf8" : "#facc15"} strokeWidth={2} />
                        )}
                        <circle r={r} fill={TYPE_COLOR[n.type]} stroke="#08080a" strokeWidth={1.5} />
                        <text
                          x={r + 4}
                          y={3}
                          fontSize={9}
                          fill="#cbd5e1"
                          style={{ pointerEvents: "none", userSelect: "none" }}
                        >
                          {n.label.length > 22 ? `${n.label.slice(0, 20)}…` : n.label}
                        </text>
                      </g>
                    );
                  })}
                </g>
              </svg>
            </div>
            <p className="mt-2 text-xs text-zinc-500">Scroll to zoom, drag the background to pan, drag a node to reposition it, click a node for details.</p>
          </div>

          <div className="space-y-4 lg:col-span-2">
            {selected ? (
              <DetailPanel node={selected} />
            ) : (
              <div className="rounded-xl border border-dashed border-white/[0.08] bg-surface-2 p-8 text-center text-sm text-zinc-500">
                Click a node in the graph to see its details.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
