import pytest

from app.services.allocate import (
    AllocationError,
    Range,
    block_size,
    find_free_slot,
    free_ranges,
    prefix_for_hosts,
    range_to_cidr_or_span,
    suggest_allocation,
    usable_hosts_for_prefix,
)
from app.services.cidr import parse_cidr


def test_usable_hosts_reserves_network_and_broadcast():
    assert usable_hosts_for_prefix(24) == 254
    assert usable_hosts_for_prefix(30) == 2
    assert usable_hosts_for_prefix(31) == 2  # point-to-point exception
    assert usable_hosts_for_prefix(32) == 1


@pytest.mark.parametrize(("hosts", "expected_prefix"), [(1, 32), (2, 31), (3, 29), (14, 28), (254, 24)])
def test_prefix_for_hosts(hosts, expected_prefix):
    assert prefix_for_hosts(hosts) == expected_prefix


def test_prefix_for_hosts_rejects_invalid():
    assert prefix_for_hosts(0) is None
    assert prefix_for_hosts(-5) is None
    assert prefix_for_hosts(2 ** 33) is None


def test_free_ranges_subtracts_occupied_gaps():
    # 10.0.0.0/24 with a used 10.0.0.64/28 in the middle
    parsed = parse_cidr("10.0.0.0/24")
    used = parse_cidr("10.0.0.64/28")
    free = free_ranges(parsed.network, parsed.broadcast, [Range(used.network, used.broadcast)])
    assert len(free) == 2
    assert free[0].start == parsed.network
    assert free[0].end == used.network - 1
    assert free[1].start == used.broadcast + 1
    assert free[1].end == parsed.broadcast


def test_find_free_slot_respects_alignment():
    # A free range starting at an address NOT aligned to the block size must
    # still only return an aligned candidate.
    free = [Range(1, 70)]  # 1..70, need an aligned /28 (16 addresses)
    slot = find_free_slot(free, 16)
    assert slot % 16 == 0
    assert slot >= 1


def test_range_to_cidr_or_span():
    assert range_to_cidr_or_span(parse_cidr("10.0.0.0/24").network, parse_cidr("10.0.0.0/24").broadcast) == "10.0.0.0/24"
    # A non-power-of-2 or unaligned range can't be one CIDR
    assert " - " in range_to_cidr_or_span(5, 20)


def test_suggest_allocation_finds_first_fit():
    parsed = parse_cidr("10.4.0.0/16")
    result = suggest_allocation(parsed.network, parsed.broadcast, parsed.prefix_len, 50, occupied=[])
    assert result.suggested_cidr == "10.4.0.0/26"
    assert result.usable_hosts == 62


def test_suggest_allocation_skips_occupied_space():
    parsed = parse_cidr("10.4.0.0/16")
    first_used = parse_cidr("10.4.0.0/26")
    result = suggest_allocation(
        parsed.network, parsed.broadcast, parsed.prefix_len, 50,
        occupied=[Range(first_used.network, first_used.broadcast)],
    )
    assert result.suggested_cidr == "10.4.0.64/26"


def test_suggest_allocation_rejects_block_as_big_as_parent():
    parsed = parse_cidr("10.9.0.0/30")
    with pytest.raises(AllocationError):
        suggest_allocation(parsed.network, parsed.broadcast, parsed.prefix_len, 100, occupied=[])


def test_suggest_allocation_reports_no_space_left():
    parsed = parse_cidr("10.9.0.0/30")  # 4 addresses total
    used = Range(parsed.network, parsed.broadcast)  # entirely occupied
    with pytest.raises(AllocationError) as exc_info:
        suggest_allocation(parsed.network, parsed.broadcast, parsed.prefix_len, 1, occupied=[used])
    assert "no free" in str(exc_info.value.message)


def test_block_size():
    assert block_size(24) == 256
    assert block_size(32) == 1
