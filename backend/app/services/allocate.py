"""Automatic subnet allocation: given a parent network's CIDR, its already-
occupied ranges, and a required host count, compute the smallest correctly
aligned free CIDR block. Pure functions, no DB access — ported from the
ip-pool-lookup tool's `lib/allocate.js` (see that tool's README for the
worked design rationale); kept pure here specifically so it's unit-testable
without a database, per the "write tests with every significant feature"
rule.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.cidr import int_to_ip


@dataclass(frozen=True)
class Range:
    start: int
    end: int


def usable_hosts_for_prefix(prefix_len: int) -> int:
    """Reserves network+broadcast for an ordinary subnet; /31 is the
    standard point-to-point exception (2 usable), /32 is a single host."""
    if prefix_len >= 32:
        return 1
    if prefix_len == 31:
        return 2
    return 2 ** (32 - prefix_len) - 2


def prefix_for_hosts(hosts: int) -> int | None:
    """Smallest prefix length (biggest number = smallest block) whose block
    fits `hosts` usable addresses. None if hosts isn't a usable positive
    whole number, or exceeds all of IPv4."""
    if not isinstance(hosts, int) or hosts < 1:
        return None
    if hosts > usable_hosts_for_prefix(0):
        return None
    for p in range(32, -1, -1):
        if usable_hosts_for_prefix(p) >= hosts:
            return p
    return None


def block_size(prefix_len: int) -> int:
    return 2 ** (32 - prefix_len)


def _align_up(addr: int, size: int) -> int:
    rem = addr % size
    return addr if rem == 0 else addr + (size - rem)


def free_ranges(range_start: int, range_end: int, occupied: list[Range]) -> list[Range]:
    """Free address ranges within [range_start, range_end] once `occupied`
    ranges are subtracted. `occupied` need not be sorted or non-overlapping."""
    free: list[Range] = []
    cursor = range_start
    for o in sorted(occupied, key=lambda r: r.start):
        if o.end < cursor:
            continue
        if o.start > cursor:
            free.append(Range(cursor, min(o.start - 1, range_end)))
        cursor = max(cursor, o.end + 1)
        if cursor > range_end:
            break
    if cursor <= range_end:
        free.append(Range(cursor, range_end))
    return [r for r in free if r.start <= r.end]


def find_free_slot(free: list[Range], size: int) -> int | None:
    """First address-aligned block of `size` addresses that fits inside any
    free range (first-fit, in address order)."""
    for r in free:
        candidate = _align_up(r.start, size)
        if candidate + size - 1 <= r.end:
            return candidate
    return None


def range_to_cidr_or_span(start: int, end: int) -> str:
    count = end - start + 1
    is_pow2 = count > 0 and (count & (count - 1)) == 0
    if is_pow2 and start % count == 0:
        prefix_len = 32 - count.bit_length() + 1
        return f"{int_to_ip(start)}/{prefix_len}"
    return f"{int_to_ip(start)} - {int_to_ip(end)}"


@dataclass
class AllocationError(Exception):
    message: str
    free: list[dict]


@dataclass
class AllocationResult:
    prefix_len: int
    usable_hosts: int
    block_size: int
    suggested_cidr: str
    free: list[dict]


def suggest_allocation(
    parent_network_addr: int,
    parent_broadcast_addr: int,
    parent_prefix_len: int,
    hosts: int,
    occupied: list[Range],
) -> AllocationResult:
    prefix_len = prefix_for_hosts(hosts)
    if prefix_len is None:
        raise AllocationError("enter a whole number of machines, 1 or more (up to what IPv4 can address)", [])
    if prefix_len <= parent_prefix_len:
        raise AllocationError(
            f"{hosts} machines needs a /{prefix_len} block, which is as big as (or bigger than) "
            "the parent network itself — pick a larger network or reduce the machine count",
            [],
        )

    free = free_ranges(parent_network_addr, parent_broadcast_addr, occupied)
    size = block_size(prefix_len)
    slot_start = find_free_slot(free, size)
    free_summary = [{"range": range_to_cidr_or_span(r.start, r.end), "addresses": r.end - r.start + 1} for r in free]

    if slot_start is None:
        largest = max((r.end - r.start + 1 for r in free), default=0)
        raise AllocationError(
            f"no free /{prefix_len} block ({size:,} addresses) left inside this network — "
            f"the largest contiguous free space is {largest:,} address{'es' if largest != 1 else ''}",
            free_summary,
        )

    return AllocationResult(
        prefix_len=prefix_len,
        usable_hosts=usable_hosts_for_prefix(prefix_len),
        block_size=size,
        suggested_cidr=f"{int_to_ip(slot_start)}/{prefix_len}",
        free=free_summary,
    )
