"""Odoo MCP strežnik za agente (Odoo 19, JSON-2 API).

Namerno izpostavi SAMO branje in ustvarjanje OSNUTKOV računov.
Ni orodja za knjiženje (action_post), brisanje ali spremembo stank/pravic.
Knjiženje izvede controller šele po odobritvi v Discordu, z drugim ključem.
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

ODOO_URL = os.environ["ODOO_URL"].rstrip("/")
ODOO_DB = os.environ.get("ODOO_DB") or None
ODOO_KEY = os.environ["ODOO_AGENT_API_KEY"]

mcp = FastMCP("odoo", host="0.0.0.0", port=8000)

INVOICE_FIELDS = ["id", "name", "partner_id", "invoice_date", "invoice_origin",
                  "amount_untaxed", "amount_total", "currency_id", "state"]


def call(model: str, method: str, **params):
    headers = {
        "Authorization": f"bearer {ODOO_KEY}",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "mge-odoo-mcp",
    }
    if ODOO_DB:
        headers["X-Odoo-Database"] = ODOO_DB
    r = httpx.post(f"{ODOO_URL}/json/2/{model}/{method}", json=params,
                   headers=headers, timeout=60)
    if r.status_code >= 400:
        try:
            err = r.json()
            msg = f"{err.get('name')}: {err.get('message')}"
        except Exception:
            msg = r.text[:500]
        raise RuntimeError(f"Odoo {model}.{method} -> HTTP {r.status_code}: {msg}")
    return r.json()


@mcp.tool()
def find_partners(name: str, limit: int = 10) -> list[dict]:
    """Poišči stranke (res.partner) po delu imena."""
    return call("res.partner", "search_read",
                domain=[["name", "ilike", name]],
                fields=["id", "name", "vat", "email", "is_company"], limit=limit)


@mcp.tool()
def find_products(name: str, limit: int = 10) -> list[dict]:
    """Poišči prodajne izdelke/storitve (product.product) po delu imena."""
    return call("product.product", "search_read",
                domain=[["name", "ilike", name], ["sale_ok", "=", True]],
                fields=["id", "name", "default_code", "list_price", "taxes_id"],
                limit=limit)


@mcp.tool()
def list_invoices(partner_id: int | None = None, date_from: str | None = None,
                  date_to: str | None = None, state: str | None = None,
                  origin_contains: str | None = None, limit: int = 50) -> list[dict]:
    """Seznam izhodnih računov. Datumi v obliki YYYY-MM-DD.
    state: draft | posted | cancel. origin_contains: iskanje po 'Izvorni dokument'."""
    domain: list = [["move_type", "=", "out_invoice"]]
    if partner_id:
        domain.append(["partner_id", "=", partner_id])
    if date_from:
        domain.append(["invoice_date", ">=", date_from])
    if date_to:
        domain.append(["invoice_date", "<=", date_to])
    if state:
        domain.append(["state", "=", state])
    if origin_contains:
        domain.append(["invoice_origin", "ilike", origin_contains])
    return call("account.move", "search_read", domain=domain,
                fields=INVOICE_FIELDS, limit=limit, order="invoice_date desc, id desc")


@mcp.tool()
def get_invoice_lines(invoice_id: int) -> list[dict]:
    """Postavke (izdelki) posameznega računa."""
    return call("account.move.line", "search_read",
                domain=[["move_id", "=", invoice_id], ["display_type", "=", "product"]],
                fields=["product_id", "name", "quantity", "price_unit",
                        "tax_ids", "price_subtotal"])


@mcp.tool()
def create_draft_invoice(partner_id: int, invoice_date: str, lines: list[dict],
                         origin: str) -> dict:
    """Ustvari OSNUTEK (draft) izhodnega računa. Knjiženja ni.
    lines: [{"product_id": int, "quantity": float, "price_unit": float, "name": str (opcijsko)}]
    origin: oznaka za idempotenco, npr. "AGENT 2026-10" (zapiše se v 'Izvorni dokument')."""
    if not lines:
        raise ValueError("Račun mora imeti vsaj eno postavko.")
    line_cmds = []
    for line in lines:
        vals = {
            "product_id": int(line["product_id"]),
            "quantity": float(line.get("quantity", 1)),
            "price_unit": float(line["price_unit"]),
        }
        if line.get("name"):
            vals["name"] = line["name"]
        line_cmds.append([0, 0, vals])

    ids = call("account.move", "create", vals_list=[{
        "move_type": "out_invoice",
        "partner_id": int(partner_id),
        "invoice_date": invoice_date,
        "invoice_origin": origin,
        "invoice_line_ids": line_cmds,
    }])
    ids = ids if isinstance(ids, list) else [ids]
    return call("account.move", "read", ids=ids, fields=INVOICE_FIELDS)[0]


if __name__ == "__main__":
    mcp.run(transport="streamable-http")   # endpoint: http://odoo-mcp:8000/mcp
