"""Configuration loading.

Locally (APP_ENV=local) values come from environment variables / a .env file.
In AWS (APP_ENV=aws) values come from a single JSON secret in AWS Secrets
Manager, so nothing sensitive lives in the Lambda's plaintext environment.

Every field here maps 1:1 to a key in .env.example.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache


def _load_dotenv_if_present() -> None:
    """Best-effort load of a local .env file. No-op if python-dotenv is absent."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - optional dependency
        return
    load_dotenv()


def _clean(mapping: dict, key: str, default: str = "") -> str:
    """Return a config value, treating blanks/unfilled placeholders as absent.

    Config never raises on missing values; instead each client validates the
    credentials it actually needs (see require_config). This lets you test one
    integration at a time locally without filling in every credential first.
    """
    value = mapping.get(key, default)
    if value is None or value == "FILL_ME":
        return default
    return value


def require_config(cfg: "Config", fields: dict, section: str) -> None:
    """Raise a clear error if any of the given {ENV_NAME: value} are blank."""
    missing = [name for name, value in fields.items() if not value]
    if missing:
        raise RuntimeError(
            f"Missing required config: {', '.join(missing)}. "
            f"Set these in your .env file (local) or Secrets Manager (aws). "
            f"See docs/SETUP.md {section}."
        )


@dataclass(frozen=True)
class Config:
    # runtime
    app_env: str
    log_level: str
    mailbox_address: str

    # google / gmail
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str

    # zoho crm
    zoho_dc: str
    zoho_client_id: str
    zoho_client_secret: str
    zoho_refresh_token: str
    zoho_module: str
    zoho_pid_field: str

    # wave
    wave_api_token: str
    wave_business_id: str
    wave_income_account_id: str

    # anthropic
    anthropic_api_key: str
    anthropic_model: str

    # aws
    aws_region: str
    ddb_table_name: str

    # google service account (optional; the durable alternative to the OAuth
    # refresh token — uses domain-wide delegation to impersonate the mailbox).
    google_service_account_file: str = ""   # path to the downloaded key JSON (local)
    google_service_account_json: str = ""   # or the key JSON inline (AWS Secrets Manager)

    # real-time push (optional — only needed for the Pub/Sub push trigger)
    pubsub_topic: str = ""       # projects/<gcp-project>/topics/<topic>
    push_audience: str = ""      # OIDC audience configured on the push subscription
    push_sa_email: str = ""      # service account email Pub/Sub signs tokens with

    # --- derived helpers -------------------------------------------------
    @property
    def zoho_accounts_base(self) -> str:
        return f"https://accounts.zoho.{self.zoho_dc}"

    @property
    def zoho_api_base(self) -> str:
        return f"https://www.zohoapis.{self.zoho_dc}/crm/v6"


def _from_mapping(m: dict) -> Config:
    return Config(
        app_env=m.get("APP_ENV", "local"),
        log_level=m.get("LOG_LEVEL", "INFO"),
        mailbox_address=_clean(m, "MAILBOX_ADDRESS"),
        google_client_id=_clean(m, "GOOGLE_CLIENT_ID"),
        google_client_secret=_clean(m, "GOOGLE_CLIENT_SECRET"),
        google_refresh_token=_clean(m, "GOOGLE_REFRESH_TOKEN"),
        google_service_account_file=_clean(m, "GOOGLE_SERVICE_ACCOUNT_FILE"),
        google_service_account_json=_clean(m, "GOOGLE_SERVICE_ACCOUNT_JSON"),
        zoho_dc=_clean(m, "ZOHO_DC", "com"),
        zoho_client_id=_clean(m, "ZOHO_CLIENT_ID"),
        zoho_client_secret=_clean(m, "ZOHO_CLIENT_SECRET"),
        zoho_refresh_token=_clean(m, "ZOHO_REFRESH_TOKEN"),
        zoho_module=_clean(m, "ZOHO_MODULE", "Deals"),
        zoho_pid_field=_clean(m, "ZOHO_PID_FIELD", "Project_ID"),
        wave_api_token=_clean(m, "WAVE_API_TOKEN"),
        wave_business_id=_clean(m, "WAVE_BUSINESS_ID"),
        wave_income_account_id=_clean(m, "WAVE_INCOME_ACCOUNT_ID"),
        anthropic_api_key=_clean(m, "ANTHROPIC_API_KEY"),
        anthropic_model=_clean(m, "ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        aws_region=m.get("AWS_REGION", "us-east-1"),
        ddb_table_name=m.get("DDB_TABLE_NAME", "invoice-request-agent-processed"),
        pubsub_topic=m.get("PUBSUB_TOPIC", ""),
        push_audience=m.get("PUSH_AUDIENCE", ""),
        push_sa_email=m.get("PUSH_SA_EMAIL", ""),
    )


def _load_from_secrets_manager() -> dict:
    """Fetch the JSON secret blob and merge it over the process environment."""
    import boto3  # imported lazily so local runs don't require it at import time

    secret_name = os.environ.get(
        "SECRETS_MANAGER_NAME", "invoice-request-agent/config"
    )
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_name)
    data = json.loads(resp["SecretString"])
    # environment (e.g. AWS_REGION, DDB_TABLE_NAME injected by Lambda) wins for
    # infra values; secret provides credentials.
    merged = {**data, **{k: v for k, v in os.environ.items()}}
    return merged


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the singleton Config, loaded from the right source for APP_ENV."""
    _load_dotenv_if_present()
    if os.environ.get("APP_ENV", "local").lower() == "aws":
        return _from_mapping(_load_from_secrets_manager())
    return _from_mapping(dict(os.environ))
