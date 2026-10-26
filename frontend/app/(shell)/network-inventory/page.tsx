"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Device = {
  id: string;
  environment_id: string;
  hostname: string;
  vendor: string | null;
  device_type: string;
  mgmt_ip: string | null;
  site: string | null;
  source: string;
  status: string;
  interface_count: number;
};

type Interface = {
  id: string;
  device_id: string;
  name: string;
  description: string | null;
  ip_address: string | null;
  mac_address: string | null;
  admin_status: string;
  oper_status: string;
  speed_mbps: number | null;
  vlan_id: number | null;
  subnet_id: string | null;
};

function StatusDot({ status }: { status: string }) {
  const up = status === "up" || status === "active";
  return (
    <span className={`inline-block h-2 w-2 rounded-full ${up ? "bg-emerald-500" : "bg-zinc-600"}`} title={status} />
  );
}

export default function NetworkInventoryPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [selected, setSelected] = useState<Device | null>(null);
  const [interfaces, setInterfaces] = useState<Interface[]>([]);
  const [q, setQ] = useState("");

  async function loadDevices() {
    const rows = await api.get<Device[]>("/devices");
    setDevices(rows);
  }

  useEffect(() => {
    loadDevices().catch(() => {});
  }, []);

  async function selectDevice(d: Device) {
    setSelected(d);
    const rows = await api.get<Interface[]>(`/devices/${d.id}/interfaces`);
    setInterfaces(rows);
  }

  const filtered = q
    ? devices.filter(
        (d) =>
          d.hostname.toLowerCase().includes(q.toLowerCase()) ||
          (d.mgmt_ip ?? "").includes(q) ||
          (d.site ?? "").toLowerCase().includes(q.toLowerCase()),
      )
    : devices;

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold text-zinc-50">Network Inventory</h1>
      <p className="mb-6 text-sm text-zinc-500">
        Devices and interfaces discovered via SNMP (mocked — see docs/ROADMAP.md for the real adapter)
      </p>

      <div className="mb-6 rounded-xl border border-white/[0.08] bg-surface-2 p-4">
        <input
          className="w-full rounded-xl border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-zinc-100"
          placeholder="Search by hostname, mgmt IP, or site"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-white/[0.08] bg-surface-2">
          <div className="border-b border-white/[0.08] px-4 py-3 text-sm font-medium text-zinc-600">
            Devices ({filtered.length})
          </div>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-zinc-500">
              <tr>
                <th className="px-4 py-2">Hostname</th>
                <th className="px-4 py-2">Type</th>
                <th className="px-4 py-2">Mgmt IP</th>
                <th className="px-4 py-2">Site</th>
                <th className="px-4 py-2">Interfaces</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((d) => (
                <tr
                  key={d.id}
                  onClick={() => selectDevice(d)}
                  className={`cursor-pointer border-t border-white/[0.08] hover:bg-white/[0.04] ${
                    selected?.id === d.id ? "bg-indigo-500/10" : ""
                  }`}
                >
                  <td className="px-4 py-2 font-medium text-zinc-100">
                    <StatusDot status={d.status} /> <span className="ml-1">{d.hostname}</span>
                  </td>
                  <td className="px-4 py-2 text-zinc-500">
                    {d.device_type}
                    {d.vendor && <span className="text-zinc-500"> · {d.vendor}</span>}
                  </td>
                  <td className="px-4 py-2 text-zinc-500">{d.mgmt_ip ?? "—"}</td>
                  <td className="px-4 py-2 text-zinc-500">{d.site ?? "—"}</td>
                  <td className="px-4 py-2 text-zinc-500">{d.interface_count}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-zinc-500">
                    No devices yet — run SNMP discovery from the API (see docs/API_SPEC.md).
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-white/[0.08] bg-surface-2 p-4">
          {!selected && <p className="text-sm text-zinc-500">Select a device to see its interfaces.</p>}
          {selected && (
            <>
              <h2 className="mb-1 text-sm font-semibold text-zinc-600">{selected.hostname} — interfaces</h2>
              <p className="mb-3 text-xs text-zinc-500">
                {selected.device_type} · {selected.vendor ?? "unknown vendor"} · {selected.site ?? "no site"} · source: {selected.source}
              </p>
              <ul className="space-y-1 text-sm">
                {interfaces.map((i) => (
                  <li key={i.id} className="rounded bg-white/[0.04] px-3 py-2">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-zinc-100">
                        <StatusDot status={i.oper_status} /> <span className="ml-1">{i.name}</span>
                      </span>
                      <span className="text-zinc-500">{i.speed_mbps ? `${i.speed_mbps} Mbps` : "—"}</span>
                    </div>
                    <div className="mt-0.5 flex justify-between text-xs text-zinc-500">
                      <span>{i.description ?? "—"}</span>
                      <span>
                        {i.ip_address ?? "no IP"}
                        {i.vlan_id != null && ` · vlan ${i.vlan_id}`}
                        {i.subnet_id && " · linked to IPAM subnet"}
                      </span>
                    </div>
                  </li>
                ))}
                {interfaces.length === 0 && <li className="text-zinc-500">No interfaces.</li>}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
