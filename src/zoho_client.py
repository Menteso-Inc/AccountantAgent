"""Zoho CRM client — look up a project's invoice details by PID.

Uses OAuth2 refresh-token flow for auth and COQL (CRM Object Query Language)
to query the Opportunities/Deals module by the custom Project ID field.

IMPORTANT — org-specific values you must confirm (docs/SETUP.md section 2):
  * ZOHO_MODULE     : the module API name (usually "Deals").
  * ZOHO_PID_FIELD  : the API name of your Project ID field (e.g. "Project_ID").
  * The field API names selected below (Deal_Name, Amount, ...) must exist in
    your org. Run scripts/inspect_zoho_module.py to list the real API names,
    then adjust FIELD_MAP if yours differ.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from .config import Config
from .models import InvoiceDetails, LineItem

logger = logging.getLogger(__name__)

# Zoho Deals field API names this client reads (confirmed via inspect_zoho_module.py
# against the menteso.com org). The Search API returns all populated fields, so we
# just read these by name in _to_invoice_details:
#   Deal_Name, Amount, Payment_Status, Invoice_Number, Client_Reference
# and the PID field from config (ZOHO_PID_FIELD = Project_ID_PID).


class ZohoClient:
    def __init__(self, config: Config):
        from .config import require_config

        require_config(
            config,
            {
                "ZOHO_CLIENT_ID": config.zoho_client_id,
                "ZOHO_CLIENT_SECRET": config.zoho_client_secret,
                "ZOHO_REFRESH_TOKEN": config.zoho_refresh_token,
            },
            "section 2",
        )
        self._cfg = config
        self._access_token: Optional[str] = None

    # --- auth ------------------------------------------------------------
    def _refresh_access_token(self) -> str:
        resp = requests.post(
            f"{self._cfg.zoho_accounts_base}/oauth/v2/token",
            params={
                "refresh_token": self._cfg.zoho_refresh_token,
                "client_id": self._cfg.zoho_client_id,
                "client_secret": self._cfg.zoho_client_secret,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"Zoho token refresh failed: {data}")
        self._access_token = data["access_token"]
        return self._access_token

    def _headers(self) -> dict:
        if not self._access_token:
            self._refresh_access_token()
        return {"Authorization": f"Zoho-oauthtoken {self._access_token}"}

    # --- query -----------------------------------------------------------
    def find_by_pid(self, pid: str) -> Optional[InvoiceDetails]:
        """Return InvoiceDetails for the Deal whose PID field == pid, or None.

        Uses the Search Records API (criteria search), which works with the
        ZohoCRM.modules.READ scope. (COQL needs a separate ZohoCRM.coql.READ scope
        that our token doesn't carry.)
        """
        module = self._cfg.zoho_module
        pid_field = self._cfg.zoho_pid_field
        params = {"criteria": f"({pid_field}:equals:{pid})"}

        def _do_search() -> requests.Response:
            return requests.get(
                f"{self._cfg.zoho_api_base}/{module}/search",
                headers=self._headers(), params=params, timeout=30,
            )

        resp = _do_search()
        if resp.status_code == 401:  # token expired mid-run -> refresh once and retry
            self._refresh_access_token()
            resp = _do_search()
        # Zoho returns 204 (no body) when nothing matches.
        if resp.status_code == 204:
            logger.info("Zoho: no %s record found for PID %s", module, pid)
            return None
        resp.raise_for_status()

        records = resp.json().get("data", [])
        if not records:
            return None
        return self._to_invoice_details(pid, records[0])

    def _to_invoice_details(self, pid: str, record: dict) -> InvoiceDetails:
        amount = float(record.get("Amount") or 0.0)
        customer = record.get("Deal_Name") or "Customer"
        ref = record.get("Client_Reference")
        # Events_or_Services is a multi-select (a list) -> normalize to a string;
        # companies.route() reads this to pick the Wave business.
        evt = record.get("Events_or_Services")
        if isinstance(evt, (list, tuple)):
            evt = ", ".join(str(x) for x in evt)
        details = InvoiceDetails(
            pid=pid,
            zoho_record_id=str(record.get("id")),
            customer_name=customer,
            customer_email=None,   # email lives on the linked Contact; wire up later
            currency="USD",        # refine if you enable multi-currency in Zoho
            status=str(record.get("Payment_Status") or ""),
            memo=f"Invoice for project {pid}" + (f" (ref {ref})" if ref else ""),
            events_or_services=evt or "",
        )
        # Single summary line item from the deal amount. Expand if your invoices
        # have itemized lines stored elsewhere in Zoho.
        details.line_items.append(
            LineItem(description=f"Services - {customer} ({pid})",
                     quantity=1.0, unit_price=amount)
        )
        return details
