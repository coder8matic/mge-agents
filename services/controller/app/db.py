import json
import os

import psycopg
from psycopg.rows import dict_row

DSN = os.environ["DATABASE_URL"]


def q(sql: str, params: tuple = (), one: bool = False):
    with psycopg.connect(DSN, row_factory=dict_row, autocommit=True) as conn:
        cur = conn.execute(sql, params)
        if cur.description is None:
            return None
        rows = cur.fetchall()
        if one:
            return rows[0] if rows else None
        return rows


def audit(actor: str, event: str, details: dict | None = None) -> None:
    q("INSERT INTO audit_log(actor, event, details) VALUES (%s, %s, %s)",
      (actor, event, json.dumps(details or {}, default=str)))
