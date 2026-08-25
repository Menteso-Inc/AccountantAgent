"""The companies the agent invoices for, and how to route a Zoho deal to one.

Each company is a separate Wave business. The routing key is the Zoho deal's
`Events_or_Services` field:

    WLF...      -> WorldLawyerForum   (ANF Global Inc.)
    IIPLA...    -> IIPLA              (International Intellectual Property Law Assn. Inc.)
    Menteso...  -> Menteso            (Menteso, Inc. — US; India entity is not used)
    anything else / blank -> None     (skip + flag; never guess the billing entity)

Business & income-account IDs are Wave GraphQL IDs — not secrets (the API token
in config is the secret). Verified against the live Wave account on 2026-08-17.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Company:
    key: str                      # short internal code
    name: str                     # display / Wave business name
    wave_business_id: str
    wave_income_account_id: str


WORLDLAWYERFORUM = Company(
    key="WLF",
    name="WorldLawyerForum (ANF Global Inc.)",
    wave_business_id="QnVzaW5lc3M6YTAwY2U4ZjAtMTUzMy00OWQ4LWI0NmItNGY5Y2QyZjU1ZTdk",
    wave_income_account_id="QWNjb3VudDo2NjQxNjkxNzU0MDg3ODU1NTY7QnVzaW5lc3M6YTAwY2U4ZjAtMTUzMy00OWQ4LWI0NmItNGY5Y2QyZjU1ZTdk",
)

IIPLA = Company(
    key="IIPLA",
    name="International Intellectual Property Law Assn. Inc.",
    wave_business_id="QnVzaW5lc3M6N2IxOTVlMzgtZjg4Ny00MjU4LWI3MGUtYjc2Y2NkZDdiNmUy",
    wave_income_account_id="QWNjb3VudDo1OTgwNjgzNjI0NTQ1NzU4Mjk7QnVzaW5lc3M6N2IxOTVlMzgtZjg4Ny00MjU4LWI3MGUtYjc2Y2NkZDdiNmUy",
)

MENTESO = Company(
    key="MENTESO",
    name="Menteso, Inc.",
    wave_business_id="QnVzaW5lc3M6NjZjMzA0OWMtZmM0ZS00NTQ0LWEyMTYtNGY4ZmUzNmMwMTFh",
    wave_income_account_id="QWNjb3VudDo1OTg0NzY5ODYzMTQyMDA2ODA7QnVzaW5lc3M6NjZjMzA0OWMtZmM0ZS00NTQ0LWEyMTYtNGY4ZmUzNmMwMTFh",
)

ALL_COMPANIES = (WORLDLAWYERFORUM, IIPLA, MENTESO)

# Match order matters only in that each keyword is distinct; checked case-insensitively.
_ROUTES = (
    ("WLF", WORLDLAWYERFORUM),
    ("IIPLA", IIPLA),
    ("MENTESO", MENTESO),
)


def _normalize(events_or_services) -> str:
    """Zoho returns this multi-select field as a list (e.g. ['WLF 2026 Europe'])."""
    if events_or_services is None:
        return ""
    if isinstance(events_or_services, (list, tuple)):
        return " ".join(str(x) for x in events_or_services).upper()
    return str(events_or_services).upper()


def route(events_or_services) -> Optional[Company]:
    """Map a deal's Events_or_Services value to a Company, or None if unrecognized."""
    text = _normalize(events_or_services)
    for keyword, company in _ROUTES:
        if keyword in text:
            return company
    return None
