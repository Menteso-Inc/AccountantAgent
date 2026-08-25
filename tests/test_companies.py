"""Routing tests — offline, no credentials.

    pytest tests/test_companies.py -v
"""
import sys

sys.path.insert(0, ".")
from src import companies  # noqa: E402


def test_route_wlf():
    assert companies.route("WLF 2026 Europe") is companies.WORLDLAWYERFORUM
    assert companies.route(["WLF GRC Summit 2027 Dubai"]) is companies.WORLDLAWYERFORUM


def test_route_iipla():
    assert companies.route("IIPLA 2026 USA") is companies.IIPLA
    assert companies.route(["IIPLA Services"]) is companies.IIPLA


def test_route_menteso():
    assert companies.route("Menteso Services") is companies.MENTESO


def test_route_unknown_or_blank_is_none():
    assert companies.route("") is None
    assert companies.route(None) is None
    assert companies.route("Some Random Event") is None


def test_each_company_has_distinct_wave_ids():
    ids = [c.wave_business_id for c in companies.ALL_COMPANIES]
    assert len(ids) == len(set(ids))
