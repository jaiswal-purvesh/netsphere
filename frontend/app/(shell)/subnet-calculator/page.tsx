"use client";

import { useMemo, useRef, useState } from "react";
import {
  buildRows,
  computeMaxDepth,
  divide,
  ipToUint32,
  joinColumnsWidth,
  joinNode,
  networkAddress,
  newLeaf,
  subnetAddresses,
  subnetLastAddress,
  subnetNetmask,
  uint32ToIp,
  type SubnetNode,
} from "@/lib/subnetCalc";

// Client-side port of the classic "Visual Subnet Calculator" (Sargasso
// Networks) tool: enter a network + mask, then divide/join subnets in a
// tree. Pure browser-side IP arithmetic — no backend calls, see
// frontend/lib/subnetCalc.ts for the math and tree-flattening logic this
// page renders.

type ColumnKey = "subnet" | "netmask" | "range" | "useable" | "hosts" | "divide" | "join";

const COLUMNS: { key: ColumnKey; label: string; default: boolean }[] = [
  { key: "subnet", label: "Subnet address", default: true },
  { key: "netmask", label: "Netmask", default: false },
  { key: "range", label: "Range of addresses", default: true },
  { key: "useable", label: "Useable IP range", default: true },
  { key: "hosts", label: "Hosts", default: true },
  { key: "divide", label: "Divide", default: true },
  { key: "join", label: "Join", default: true },
];

export default function SubnetCalculatorPage() {
  const [networkInput, setNetworkInput] = useState("192.168.0.0");
  const [maskInput, setMaskInput] = useState("24");
  const [formError, setFormError] = useState<string | null>(null);

  const [baseAddress, setBaseAddress] = useState<number | null>(null);
  const [baseMask, setBaseMask] = useState<number | null>(null);
  const rootRef = useRef<SubnetNode>(newLeaf());
  const [, setRevision] = useState(0);
  const rerender = () => setRevision((r) => r + 1);

  const [visible, setVisible] = useState<Record<ColumnKey, boolean>>(() => {
    const initial = {} as Record<ColumnKey, boolean>;
    for (const c of COLUMNS) initial[c.key] = c.default;
    return initial;
  });

  function onUpdate(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    const ip = ipToUint32(networkInput);
    if (ip === null) {
      setFormError("Enter a valid network address, e.g. 192.168.0.0");
      return;
    }
    const mask = Number(maskInput);
    if (!Number.isInteger(mask) || mask < 0 || mask > 32) {
      setFormError("Mask bits must be a whole number between 0 and 32.");
      return;
    }

    const network = networkAddress(ip, mask);
    if (network !== ip) {
      // Not on a subnet boundary for this mask — snap it, same as the
      // original tool, and let the user see the corrected address.
      setNetworkInput(uint32ToIp(network));
    }

    if (baseMask !== null && rootRef.current.left) {
      if (!window.confirm("Changing the base network or mask will discard all current divisions. Continue?")) {
        return;
      }
    }

    rootRef.current = newLeaf();
    setBaseAddress(network);
    setBaseMask(mask);
    rerender();
  }

  function onReset() {
    if (rootRef.current.left && !window.confirm("Discard all current divisions?")) return;
    rootRef.current = newLeaf();
    rerender();
  }

  const maxDepth = baseAddress !== null ? computeMaxDepth(rootRef.current) : 0;
  const rows = useMemo(() => {
    if (baseAddress === null || baseMask === null) return [];
    return buildRows(rootRef.current, baseAddress, baseMask, maxDepth);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rootRef mutates in place; `revision` (folded into maxDepth via rerender) is the real dependency
  }, [baseAddress, baseMask, maxDepth]);

  const joinWidth = baseAddress !== null ? joinColumnsWidth(rootRef.current, maxDepth) : 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-zinc-50">Subnet Calculator</h2>
        <p className="text-sm text-zinc-500">
          Enter a network address and mask, then divide or join subnets to plan your addressing.
        </p>
      </div>

      <form onSubmit={onUpdate} className="flex flex-wrap items-end gap-4 rounded-xl border border-white/[0.08] bg-surface-2 p-4">
        <label className="text-sm text-zinc-500">
          Network address
          <input
            className="mt-1 block w-44 rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
            value={networkInput}
            onChange={(e) => setNetworkInput(e.target.value)}
            placeholder="192.168.0.0"
          />
        </label>
        <label className="text-sm text-zinc-500">
          Mask bits
          <input
            className="mt-1 block w-24 rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
            value={maskInput}
            onChange={(e) => setMaskInput(e.target.value)}
            type="number"
            min={0}
            max={32}
          />
        </label>
        <button
          type="submit"
          className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
        >
          Update
        </button>
        <button
          type="button"
          onClick={onReset}
          className="rounded-xl border border-white/[0.08] px-4 py-2 text-sm font-medium text-zinc-500 hover:bg-white/[0.04]"
        >
          Reset divisions
        </button>
        {formError && <p className="w-full text-sm text-red-400">{formError}</p>}
      </form>

      {baseAddress !== null && baseMask !== null && (
        <>
          <div className="flex flex-wrap gap-4 rounded-xl border border-white/[0.08] bg-surface-2 p-4 text-sm text-zinc-500">
            {COLUMNS.map((c) => (
              <label key={c.key} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={visible[c.key]}
                  onChange={(e) => setVisible((v) => ({ ...v, [c.key]: e.target.checked }))}
                />
                {c.label}
              </label>
            ))}
          </div>

          <div className="overflow-x-auto rounded-xl border border-white/[0.08] bg-surface-2">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-white/[0.08] bg-white/[0.04] text-left text-xs font-medium uppercase tracking-wide text-zinc-500">
                  {visible.subnet && <th className="px-3 py-2">Subnet address</th>}
                  {visible.netmask && <th className="px-3 py-2">Netmask</th>}
                  {visible.range && <th className="px-3 py-2">Range of addresses</th>}
                  {visible.useable && <th className="px-3 py-2">Useable IP range</th>}
                  {visible.hosts && <th className="px-3 py-2 text-right">Hosts</th>}
                  {visible.divide && <th className="px-3 py-2">Divide</th>}
                  {visible.join && (
                    <th className="px-3 py-2" colSpan={joinWidth}>
                      Join
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const last = subnetLastAddress(row.address, row.mask);
                  const hosts = row.mask >= 31 ? subnetAddresses(row.mask) : subnetAddresses(row.mask) - 2;
                  const useableFirst = row.mask >= 31 ? row.address : row.address + 1;
                  const useableLast = row.mask >= 31 ? last : last - 1;
                  return (
                    <tr key={`${row.address}-${row.mask}`} className="border-b border-white/[0.08] last:border-0">
                      {visible.subnet && (
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-zinc-100">
                          {uint32ToIp(row.address)}/{row.mask}
                        </td>
                      )}
                      {visible.netmask && (
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-zinc-500">
                          {uint32ToIp(subnetNetmask(row.mask))}
                        </td>
                      )}
                      {visible.range && (
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-zinc-500">
                          {uint32ToIp(row.address)} - {uint32ToIp(last)}
                        </td>
                      )}
                      {visible.useable && (
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-zinc-500">
                          {hosts > 0 ? `${uint32ToIp(useableFirst)} - ${uint32ToIp(useableLast)}` : "—"}
                        </td>
                      )}
                      {visible.hosts && <td className="px-3 py-2 text-right text-zinc-500">{Math.max(hosts, 0)}</td>}
                      {visible.divide && (
                        <td className="px-3 py-2">
                          <button
                            type="button"
                            disabled={row.mask >= 32}
                            onClick={() => {
                              divide(row.node);
                              rerender();
                            }}
                            className="rounded-xl border border-white/[0.08] px-2 py-1 text-xs font-medium text-zinc-500 hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            Divide
                          </button>
                        </td>
                      )}
                      {visible.join &&
                        row.joinCells.map((cell, i) => (
                          <td
                            key={i}
                            rowSpan={cell.rowSpan}
                            colSpan={cell.colSpan}
                            className="border-l border-white/[0.08] px-2 py-1 text-center align-middle"
                          >
                            {cell.rowSpan > 1 || cell.colSpan > 1 ? (
                              <button
                                type="button"
                                onClick={() => {
                                  joinNode(cell.node);
                                  rerender();
                                }}
                                title={`Join back into /${cell.mask - 1}`}
                                className="w-full rounded-xl bg-indigo-500/10 px-2 py-1 text-xs font-medium text-indigo-400 hover:bg-indigo-500/20"
                              >
                                /{cell.mask}
                              </button>
                            ) : (
                              <span className="text-xs text-zinc-500">/{cell.mask}</span>
                            )}
                          </td>
                        ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
