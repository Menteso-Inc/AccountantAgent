"""Wave client — create (or reuse) an invoice in the RIGHT company's Wave business.

Model (confirmed by schema introspection against the live Wave account):
  * The company/business is chosen by the pipeline (src/companies.py) from the
    Zoho deal's Events_or_Services; this client is told which business to use.
  * Invoice line items must reference a Product; we keep one reusable
    "Professional Services (automated)" product per business and override
    description/price per line. Attendees (event delegates) are named in the line.
  * The PID is stamped into `poNumber` — used to find/reuse an existing invoice
    for a PID (one invoice per PID) and for traceability.
  * Discounts are applied as a FIXED-amount invoice discount.
  * Invoices are created SAVED (approved, numbered, has a branded PDF from the
    business's own logo) — Wave does NOT auto-email; the agent sends the PDF.
  * Marking an invoice PAID is possible via invoicePaymentCreateManual but needs
    a per-business deposit account; that wiring is pending, so a "paid" request is
    logged and the invoice is left SAVED for now (safe — a human can mark it paid).

Requires a paid Wave plan (Pro/Advisor).
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from .companies import Company
from .config import Config
from .models import GeneratedInvoice, InvoiceDetails

logger = logging.getLogger(__name__)

WAVE_ENDPOINT = "https://gql.waveapps.com/graphql/public"
SERVICE_PRODUCT_NAME = "Professional Services (automated)"
_MAX_SEARCH_PAGES = 20

_INVOICES_BY_PAGE = """
query ($businessId: ID!, $page: Int!) {
  business(id: $businessId) {
    invoices(page: $page, pageSize: 50) {
      pageInfo { currentPage totalPages }
      edges { node { id poNumber invoiceNumber status pdfUrl viewUrl } } }
  }
}
"""
_CUSTOMERS_BY_PAGE = """
query ($businessId: ID!, $page: Int!) {
  business(id: $businessId) {
    customers(page: $page, pageSize: 50) {
      pageInfo { currentPage totalPages }
      edges { node { id name email } } }
  }
}
"""
_PRODUCTS_BY_PAGE = """
query ($businessId: ID!, $page: Int!) {
  business(id: $businessId) {
    products(page: $page, pageSize: 50) {
      pageInfo { currentPage totalPages }
      edges { node { id name } } }
  }
}
"""
_INVOICE_BY_ID = """
query ($id: ID!) { invoice(id: $id) { id poNumber invoiceNumber status pdfUrl viewUrl } }
"""
_CUSTOMER_CREATE = """
mutation ($input: CustomerCreateInput!) {
  customerCreate(input: $input) {
    didSucceed inputErrors { code message path } customer { id name } }
}
"""
_PRODUCT_CREATE = """
mutation ($input: ProductCreateInput!) {
  productCreate(input: $input) {
    didSucceed inputErrors { code message path } product { id name } }
}
"""
_INVOICE_CREATE = """
mutation ($input: InvoiceCreateInput!) {
  invoiceCreate(input: $input) {
    didSucceed inputErrors { code message path }
    invoice { id invoiceNumber status poNumber pdfUrl viewUrl } }
}
"""


class WaveClient:
    def __init__(self, config: Config):
        self._cfg = config
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {config.wave_api_token}",
             "Content-Type": "application/json"}
        )
        self._product_by_business: dict[str, str] = {}  # cache per business

    def _gql(self, query: str, variables: dict) -> dict:
        resp = self._session.post(
            WAVE_ENDPOINT, json={"query": query, "variables": variables}, timeout=45
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"Wave GraphQL error: {payload['errors']}")
        return payload["data"]

    # --- dedupe by PID (within the given business) ----------------------
    def find_invoice_by_pid(self, business_id: str, pid: str) -> Optional[dict]:
        page = 1
        while page <= _MAX_SEARCH_PAGES:
            conn = self._gql(_INVOICES_BY_PAGE,
                             {"businessId": business_id, "page": page})["business"]["invoices"]
            for edge in conn["edges"]:
                if (edge["node"].get("poNumber") or "") == pid:
                    return edge["node"]
            if page >= conn["pageInfo"]["totalPages"]:
                break
            page += 1
        return None

    # --- reusable product ------------------------------------------------
    def ensure_service_product(self, business_id: str, income_account_id: str) -> str:
        if business_id in self._product_by_business:
            return self._product_by_business[business_id]
        page = 1
        while page <= _MAX_SEARCH_PAGES:
            conn = self._gql(_PRODUCTS_BY_PAGE,
                             {"businessId": business_id, "page": page})["business"]["products"]
            for edge in conn["edges"]:
                if edge["node"]["name"] == SERVICE_PRODUCT_NAME:
                    self._product_by_business[business_id] = edge["node"]["id"]
                    return edge["node"]["id"]
            if page >= conn["pageInfo"]["totalPages"]:
                break
            page += 1
        result = self._gql(_PRODUCT_CREATE, {"input": {
            "businessId": business_id, "name": SERVICE_PRODUCT_NAME,
            "unitPrice": 0, "incomeAccountId": income_account_id,
        }})["productCreate"]
        if not result["didSucceed"]:
            raise RuntimeError(f"Wave productCreate failed: {result['inputErrors']}")
        pid_ = result["product"]["id"]
        self._product_by_business[business_id] = pid_
        return pid_

    # --- customer --------------------------------------------------------
    def ensure_customer(self, business_id: str, details: InvoiceDetails) -> str:
        want_name = details.customer_name.strip().lower()
        want_email = (details.customer_email or "").strip().lower()
        page = 1
        while page <= _MAX_SEARCH_PAGES:
            conn = self._gql(_CUSTOMERS_BY_PAGE,
                             {"businessId": business_id, "page": page})["business"]["customers"]
            for edge in conn["edges"]:
                node = edge["node"]
                if node["name"].strip().lower() == want_name or (
                    want_email and (node.get("email") or "").strip().lower() == want_email
                ):
                    return node["id"]
            if page >= conn["pageInfo"]["totalPages"]:
                break
            page += 1
        cust = {"businessId": business_id, "name": details.customer_name}
        if details.customer_email:
            cust["email"] = details.customer_email
        result = self._gql(_CUSTOMER_CREATE, {"input": cust})["customerCreate"]
        if not result["didSucceed"]:
            raise RuntimeError(f"Wave customerCreate failed: {result['inputErrors']}")
        return result["customer"]["id"]

    # --- create ----------------------------------------------------------
    def create_invoice(self, business_id: str, details: InvoiceDetails,
                       customer_id: str, product_id: str) -> dict:
        base = details.line_items[0] if details.line_items else None
        description = base.description if base else f"Services ({details.pid})"
        quantity = base.quantity if base else 1.0
        unit_price = base.unit_price if base else 0.0
        if details.attendees:  # option (a): total unchanged, attendees named on the line
            names = "; ".join(a.name for a in details.attendees)
            description = f"{description}\nAttendees: {names}"

        invoice_input = {
            "businessId": business_id,
            "customerId": customer_id,
            "status": "SAVED",
            "currency": details.currency or "USD",
            "poNumber": details.pid,          # PID stamped here
            "memo": details.memo,
            "items": [{"productId": product_id, "description": description,
                       "quantity": quantity, "unitPrice": unit_price}],
        }
        if details.discount_amount and details.discount_amount > 0:
            invoice_input["discounts"] = [{
                "discountType": "FIXED", "name": "Discount",
                "amount": details.discount_amount,
            }]
        result = self._gql(_INVOICE_CREATE, {"input": invoice_input})["invoiceCreate"]
        if not result["didSucceed"]:
            raise RuntimeError(f"Wave invoiceCreate failed: {result['inputErrors']}")
        return result["invoice"]

    # --- orchestration ---------------------------------------------------
    def generate(self, details: InvoiceDetails, company: Company) -> GeneratedInvoice:
        """One invoice per PID in the routed company's business. Returns the PDF."""
        from .config import require_config
        require_config(self._cfg, {"WAVE_API_TOKEN": self._cfg.wave_api_token}, "section 3")
        bid = company.wave_business_id

        invoice = self.find_invoice_by_pid(bid, details.pid)
        if invoice:
            logger.info("Reusing Wave invoice %s for PID %s in %s",
                        invoice.get("invoiceNumber"), details.pid, company.name)
        else:
            customer_id = self.ensure_customer(bid, details)
            product_id = self.ensure_service_product(bid, company.wave_income_account_id)
            invoice = self.create_invoice(bid, details, customer_id, product_id)
            logger.info("Created Wave invoice %s for PID %s in %s",
                        invoice.get("invoiceNumber"), details.pid, company.name)

        if details.is_paid:
            # invoicePaymentCreateManual needs a per-business deposit account (not yet
            # wired). Leave SAVED (unpaid) rather than fake it; flag for follow-up.
            logger.warning("PID %s requested PAID — payment recording not yet wired; "
                           "invoice left SAVED. Mark paid in Wave for now.", details.pid)

        pdf_url = invoice.get("pdfUrl")
        if not pdf_url:
            invoice = self._gql(_INVOICE_BY_ID, {"id": invoice["id"]})["invoice"]
            pdf_url = invoice.get("pdfUrl")
        if not pdf_url:
            raise RuntimeError(f"Wave invoice {invoice.get('id')} has no pdfUrl")

        return GeneratedInvoice(
            wave_invoice_id=invoice["id"],
            invoice_number=invoice.get("invoiceNumber", ""),
            pdf_bytes=self._download_pdf(pdf_url),
            view_url=invoice.get("viewUrl", ""),
            status=invoice.get("status", ""),
        )

    def _download_pdf(self, pdf_url: str) -> bytes:
        resp = requests.get(
            pdf_url, headers={"Authorization": f"Bearer {self._cfg.wave_api_token}"}, timeout=60,
        )
        resp.raise_for_status()
        return resp.content
