CREATE EXTENSION IF NOT EXISTS vector;   -- for agent memory (F1+)

CREATE TABLE runs (
  id           BIGSERIAL PRIMARY KEY,
  agent        TEXT NOT NULL,
  trigger      TEXT NOT NULL,                     -- schedule | discord
  requested_by TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'running',   -- running | awaiting_approval | done | rejected | failed
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  cost_usd     NUMERIC(10,4),
  summary      TEXT,
  error        TEXT
);

CREATE TABLE approvals (
  id           BIGSERIAL PRIMARY KEY,
  run_id       BIGINT NOT NULL REFERENCES runs(id),
  action       TEXT NOT NULL,                     -- e.g. odoo.post_invoices
  payload      JSONB NOT NULL,                    -- {"invoice_ids": [...]}
  status       TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected | executed | failed
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_by   TEXT,
  decided_at   TIMESTAMPTZ,
  result       JSONB
);

-- Audit trail: INSERT only (append-only)
CREATE TABLE audit_log (
  id      BIGSERIAL PRIMARY KEY,
  at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor   TEXT NOT NULL,
  event   TEXT NOT NULL,
  details JSONB
);
CREATE RULE audit_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;
