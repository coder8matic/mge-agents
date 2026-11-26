"""Controller's Odoo access: only finding the agent's drafts and posting AFTER approval.
Uses ODOO_APPROVER_API_KEY (the agent never sees this key)."""
import os

import httpx

ODOO_URL = os.environ["ODOO_URL"].rstrip("/")
ODOO_DB = os.environ.get("ODOO_DB") or None
APPROVER_KEY = os.environ["ODOO_APPROVER_API_KEY"]
AGENT_UID = int(os.environ["ODOO_AGENT_USER_ID"])

FIELDS = ["id", "name", "partner_id", "invoice_date", "invoice_origin",
          "amount_untaxed", "amount_total", "currency_id", "state", "create_uid"]


def call(model: str, method: str, **params):
    headers = {
        "Authorization": f"bearer {APPROVER_KEY}",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "mge-controller",
    }
    if ODOO_DB:
        headers["X-Odoo-Database"] = ODOO_DB
    r = httpx.post(f"{ODOO_URL}/json/2/{model}/{method}", json=params,
                   headers=headers, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Odoo {model}.{method} -> HTTP {r.status_code}: {r.text[:500]}")
    return r.json()


def agent_drafts_since(since_utc: str) -> list[dict]:
    """Draft customer invoices created by the agent since 'since_utc' (YYYY-MM-DD HH:MM:SS)."""
    return call("account.move", "search_read", domain=[
        ["move_type", "=", "out_invoice"],
        ["state", "=", "draft"],
        ["create_uid", "=", AGENT_UID],
        ["create_date", ">=", since_utc],
    ], fields=FIELDS, order="id")


def post_invoices(ids: list[int]) -> list[dict]:
    """Post invoices. First re-check that they are still the agent's drafts."""
    current = call("account.move", "read", ids=ids,
                   fields=["id", "state", "create_uid", "move_type"])
    bad = [r for r in current
           if r["state"] != "draft" or r["move_type"] != "out_invoice"
           or not r["create_uid"] or r["create_uid"][0] != AGENT_UID]
    if bad or len(current) != len(ids):
        raise RuntimeError(f"Invoices are no longer valid agent drafts: {bad or 'records missing'}")
    call("account.move", "action_post", ids=ids)
    return call("account.move", "read", ids=ids,
                fields=["id", "name", "state", "amount_total"])
