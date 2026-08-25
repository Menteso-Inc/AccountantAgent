"""Offline tests for the push-request verifier.

Only the disabled and missing/malformed-token paths are covered here — those need
no network. Real token-signature verification is exercised end-to-end against
Google in section 6f of docs/SETUP.md.

    pytest tests/test_oidc.py -v
"""
import sys

sys.path.insert(0, ".")
from src.oidc import verify_push_request  # noqa: E402


def test_disabled_when_no_audience_or_sa():
    # No expected audience/SA configured -> verification disabled -> accept.
    assert verify_push_request("Bearer whatever", "", "") is True


def test_rejects_missing_bearer_when_enabled():
    assert verify_push_request(None, "aud", "sa@x.iam.gserviceaccount.com") is False


def test_rejects_non_bearer_header_when_enabled():
    assert verify_push_request("Basic abc", "aud", "sa@x.iam.gserviceaccount.com") is False
