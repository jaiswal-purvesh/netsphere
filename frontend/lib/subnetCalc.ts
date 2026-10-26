/**
 * Pure subnet-division math for the Subnet Calculator page — ported from the
 * classic "Visual Subnet Calculator" (Sargasso Networks) tool the user
 * supplied, reworked from imperative DOM manipulation into a small,
 * immutable-data-friendly tree the React page can render.
 *
 * The IPv4 helpers (ipToUint32/uint32ToIp/networkAddress/subnetAddresses/
 * subnetLastAddress/subnetNetmask) are a direct, verified port of the
 * original tool's inet_aton/inet_ntoa/network_address/subnet_addresses/
 * subnet_last_address/subnet_netmask — including relying on the same
 * JS-bitwise-ops-on-32-bit-values trick the original used (safe here because
 * every address stays an exact integer under Number.MAX_SAFE_INTEGER, and
 * JS's ToInt32 coercion inside `&`/`>>` is self-consistent across the plain
 * arithmetic `+` used elsewhere).
 *
 * The tree/row layout (countLeaves/computeMaxDepth/buildRows) replaces the
 * original's DOM-recursion-with-shared-vs-fresh-array trick for the "Join"
 * pyramid column with an explicit, verified-by-construction equivalent: for
 * every leaf we record which ancestor "tiers" it is responsible for
 * rendering (rowSpan cells only ever get emitted once, by the leftmost leaf
 * under that ancestor) and how wide its deepest owned cell needs to be to
 * keep every row's total column width equal to the tree's overall depth.
 * See the dev notes at the bottom of this file for the width-consistency
 * proof this was checked against.
 */

export type SubnetNode = {
  left: SubnetNode | null;
  right: SubnetNode | null;
};

export function newLeaf(): SubnetNode {
  return { left: null, right: null };
}

export function isLeaf(node: SubnetNode): boolean {
  return node.left === null || node.right === null;
}

export function divide(node: SubnetNode): void {
  node.left = newLeaf();
  node.right = newLeaf();
}

export function joinNode(node: SubnetNode): void {
  node.left = null;
  node.right = null;
}

/** Parse "a.b.c.d" into a uint32 (as a JS number), or null if invalid. */
export function ipToUint32(addrstr: string): number | null {
  const re = /^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$/;
  const res = re.exec(addrstr.trim());
  if (res === null) return null;
  const parts = [Number(res[1]), Number(res[2]), Number(res[3]), Number(res[4])];
  for (const p of parts) {
    if (p < 0 || p > 255) return null;
  }
  return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3];
}

export function uint32ToIp(addrint: number): string {
  return [
    (addrint >> 24) & 0xff,
    (addrint >> 16) & 0xff,
    (addrint >> 8) & 0xff,
    addrint & 0xff,
  ].join(".");
}

export function networkAddress(ip: number, mask: number): number {
  let result = ip;
  for (let i = 31 - mask; i >= 0; i--) {
    result &= ~(1 << i);
  }
  return result;
}

export function subnetAddresses(mask: number): number {
  return 2 ** (32 - mask);
}

export function subnetLastAddress(subnet: number, mask: number): number {
  return subnet + subnetAddresses(mask) - 1;
}

export function subnetNetmask(mask: number): number {
  return networkAddress(0xffffffff, mask);
}

export function countLeaves(node: SubnetNode): number {
  if (!node.left || !node.right) return 1;
  return countLeaves(node.left) + countLeaves(node.right);
}

/** Edges from this node down to its deepest leaf (0 if node is itself a leaf). */
export function computeMaxDepth(node: SubnetNode): number {
  if (!node.left || !node.right) return 0;
  return 1 + Math.max(computeMaxDepth(node.left), computeMaxDepth(node.right));
}

export type JoinCell = {
  mask: number;
  rowSpan: number;
  colSpan: number;
  node: SubnetNode; // clicking this cell joins (collapses) this node's children
};

export type LeafRow = {
  address: number;
  mask: number;
  node: SubnetNode; // the leaf itself — divide() targets this
  leafDepth: number;
  joinCells: JoinCell[]; // only the cells THIS row is responsible for rendering
};

/**
 * Flattens the tree into one row per leaf subnet, in address order, with
 * each row's "owned" join-column cells (see module docstring). `maxDepth`
 * must be `computeMaxDepth(root)` — passed in rather than recomputed per
 * call since callers usually need it for the header width too.
 */
export function buildRows(root: SubnetNode, baseAddress: number, baseMask: number, maxDepth: number): LeafRow[] {
  function walk(
    node: SubnetNode,
    address: number,
    mask: number,
    ownedSoFar: JoinCell[],
    leafDepth: number,
  ): LeafRow[] {
    if (node.left && node.right) {
      const leftOwned = [...ownedSoFar, { mask: mask + 1, rowSpan: countLeaves(node.left), colSpan: 1, node }];
      const rightOwned: JoinCell[] = [{ mask: mask + 1, rowSpan: countLeaves(node.right), colSpan: 1, node }];
      return [
        ...walk(node.left, address, mask + 1, leftOwned, leafDepth + 1),
        ...walk(node.right, address + subnetAddresses(mask + 1), mask + 1, rightOwned, leafDepth + 1),
      ];
    }
    // Fix up the colSpan of the deepest (last) owned cell so every row's
    // total rendered+spanned-over width equals the header's total width.
    const fixed = ownedSoFar.map((cell, i) =>
      i === ownedSoFar.length - 1 ? { ...cell, colSpan: 1 + (maxDepth - leafDepth) } : cell,
    );
    return [{ address, mask, node, leafDepth, joinCells: fixed }];
  }

  return walk(root, baseAddress, baseMask, [{ mask: baseMask, rowSpan: countLeaves(root), colSpan: 1, node: root }], 0);
}

export function joinColumnsWidth(root: SubnetNode, maxDepth: number): number {
  return root.left ? maxDepth + 1 : 1;
}

/*
Dev note — width-consistency proof this was checked against (see the
divide/join sequences run against a standalone port of this exact logic
before it was wired into the page):

  Test1 (undivided):                  header=1  row0 total=1
  Test2 (root split once):            header=2  row0=2, row1=2
  Test3 (+ one child split again):    header=3  row0=3, row1=3, row2=3
  Test4 (+ deeper split on one leg):  header=4  rows all =4
  Test5 (asymmetric, both legs split):header=4  rows all =4
  Test6 (join one branch back):       header=4  rows all =4

Every row's (sum of its own joinCells' colSpan) + (colSpan carried over from
an ancestor's rowSpan reaching down into this row) equals the header's total
width in every case, including after a join collapses part of the tree.
*/
