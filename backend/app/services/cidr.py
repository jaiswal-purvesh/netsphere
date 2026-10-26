"""IPv4 CIDR math. Direct port of the ip-pool-lookup tool's `lib/cidr.js`,
kept dependency-free (no `ipaddress` module quirks to fight — this is
simple enough to own outright, same rationale as the original).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CIDR_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})/(\d{1,2})$")
_IP_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


class CidrError(ValueError):
    pass


def ip_to_int(ip: str) -> int:
    m = _IP_RE.match(ip.strip())
    if not m:
        raise CidrError(f'"{ip}" is not a valid IPv4 address')
    octets = [int(g) for g in m.groups()]
    if any(o > 255 for o in octets):
        raise CidrError(f'"{ip}" is not a valid IPv4 address')
    n = 0
    for o in octets:
        n = (n << 8) | o
    return n


def int_to_ip(n: int) -> str:
    return ".".join(str((n >> shift) & 255) for shift in (24, 16, 8, 0))


def is_valid_ip(ip: str) -> bool:
    try:
        ip_to_int(ip)
        return True
    except CidrError:
        return False


@dataclass(frozen=True)
class ParsedCidr:
    cidr: str
    network: int
    broadcast: int
    prefix_len: int


def parse_cidr(raw: str) -> ParsedCidr:
    raw = str(raw).strip()
    m = _CIDR_RE.match(raw)
    if not m:
        raise CidrError(f'"{raw}" is not a valid IPv4 CIDR (expected e.g. 10.0.0.0/16)')
    ip_part = ".".join(m.groups()[:4])
    prefix_len = int(m.group(5))
    if prefix_len < 0 or prefix_len > 32:
        raise CidrError(f'"{raw}" has an invalid prefix length (0-32)')
    ip = ip_to_int(ip_part)

    host_bits = 32 - prefix_len
    mask = 0 if host_bits == 32 else (0xFFFFFFFF << host_bits) & 0xFFFFFFFF
    network = ip & mask
    broadcast = network | (~mask & 0xFFFFFFFF)

    return ParsedCidr(cidr=f"{int_to_ip(network)}/{prefix_len}", network=network, broadcast=broadcast, prefix_len=prefix_len)
