"""Verify that a Pub/Sub push request genuinely came from Google.

The push endpoint (API Gateway) is public, so we must authenticate callers.
Pub/Sub can attach a Google-signed OIDC JWT (configured on the subscription).
We verify its signature, audience, and the service-account email claim.

If neither PUSH_AUDIENCE nor PUSH_SA_EMAIL is configured, verification is
disabled (useful for local testing) and a warning is logged.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def verify_push_request(
    auth_header: Optional[str],
    expected_audience: str,
    expected_sa_email: str,
) -> bool:
    if not expected_audience and not expected_sa_email:
        logger.warning("OIDC verification disabled (no PUSH_AUDIENCE/PUSH_SA_EMAIL set)")
        return True

    if not auth_header or not auth_header.lower().startswith("bearer "):
        logger.warning("Push request missing bearer token")
        return False

    token = auth_header.split(" ", 1)[1].strip()

    # Imported lazily so unit tests of the disabled/missing-token paths need no SDK.
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_oauth2_token(
            token, g_requests.Request(), audience=expected_audience or None
        )
    except Exception:
        logger.exception("OIDC token verification failed")
        return False

    if expected_sa_email and claims.get("email") != expected_sa_email:
        logger.warning("OIDC email mismatch: got %s", claims.get("email"))
        return False

    return True
