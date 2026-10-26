import pytest

from app.services.cidr import CidrError, int_to_ip, ip_to_int, is_valid_ip, parse_cidr


def test_ip_round_trip():
    assert int_to_ip(ip_to_int("10.4.12.37")) == "10.4.12.37"


def test_ip_to_int_rejects_garbage():
    with pytest.raises(CidrError):
        ip_to_int("999.1.1.1")
    with pytest.raises(CidrError):
        ip_to_int("not-an-ip")


def test_is_valid_ip():
    assert is_valid_ip("10.0.0.1") is True
    assert is_valid_ip("10.0.0.999") is False


def test_parse_cidr_basic():
    parsed = parse_cidr("10.4.0.0/16")
    assert parsed.cidr == "10.4.0.0/16"
    assert parsed.prefix_len == 16
    assert int_to_ip(parsed.network) == "10.4.0.0"
    assert int_to_ip(parsed.broadcast) == "10.4.255.255"


def test_parse_cidr_normalizes_non_network_address():
    # 10.4.1.5/24 should normalize down to the network address 10.4.1.0/24
    parsed = parse_cidr("10.4.1.5/24")
    assert parsed.cidr == "10.4.1.0/24"


def test_parse_cidr_rejects_bad_prefix():
    with pytest.raises(CidrError):
        parse_cidr("10.0.0.0/33")


def test_parse_cidr_rejects_malformed():
    with pytest.raises(CidrError):
        parse_cidr("not a cidr")
