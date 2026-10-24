-- Red Ledger canonical schema. Applied by battlefield at startup (idempotent).
-- Change this file ONLY via a contracts/ PR with a CHANGELOG entry.
-- Conventions: text ids with prefixes (ep_, ven_, inv_, ...), integer "day" = simulated business day
-- within an episode (0-based), money as NUMERIC(14,2), timestamps UTC.
-- `origin` is provenance for scoring: 'sim' (seeded/legit), 'red', 'green', 'blue'.
-- Battlefield NEVER returns `origin` to any X-Agent caller.

CREATE TABLE IF NOT EXISTS episodes (
  id               TEXT PRIMARY KEY,
  seed             INTEGER NOT NULL,
  controller_mode  TEXT NOT NULL CHECK (controller_mode IN ('off','shadow','enforce')),
  days             INTEGER NOT NULL DEFAULT 10,
  status           TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created','running','paused','finished','failed')),
  current_day      INTEGER NOT NULL DEFAULT 0,
  attack_plan      JSONB,                       -- optional forced schedule: [{day, scheme_id, params}]
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at       TIMESTAMPTZ,
  finished_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS vendors (
  id            TEXT PRIMARY KEY,
  episode_id    TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  ein           TEXT,
  bank_account  TEXT NOT NULL,
  bank_routing  TEXT NOT NULL,
  address       TEXT,
  category      TEXT,                           -- e.g. 'office','logistics','it','facilities'
  created_day   INTEGER NOT NULL,               -- negative for pre-episode history
  status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','frozen')),
  origin        TEXT NOT NULL DEFAULT 'sim',
  created_by    TEXT                            -- agent or 'seed'
);
CREATE INDEX IF NOT EXISTS vendors_ep ON vendors(episode_id);

CREATE TABLE IF NOT EXISTS vendor_changes (
  id             TEXT PRIMARY KEY,
  episode_id     TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  vendor_id      TEXT NOT NULL REFERENCES vendors(id),
  field          TEXT NOT NULL CHECK (field IN ('bank_account','bank_routing','address','name')),
  old_value      TEXT,
  new_value      TEXT NOT NULL,
  justification  TEXT,
  requested_day  INTEGER NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','blocked')),
  resolved_day   INTEGER,
  origin         TEXT NOT NULL DEFAULT 'sim'
);
CREATE INDEX IF NOT EXISTS vendor_changes_ep ON vendor_changes(episode_id, status);

CREATE TABLE IF NOT EXISTS employees (
  id            TEXT PRIMARY KEY,
  episode_id    TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  role          TEXT NOT NULL,
  department    TEXT,
  salary        NUMERIC(14,2) NOT NULL,
  bank_account  TEXT NOT NULL,
  start_day     INTEGER NOT NULL,
  status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','terminated','frozen')),
  hr_record     BOOLEAN NOT NULL DEFAULT true,  -- false = no onboarding record (ghost employee signal)
  origin        TEXT NOT NULL DEFAULT 'sim'
);
CREATE INDEX IF NOT EXISTS employees_ep ON employees(episode_id);

CREATE TABLE IF NOT EXISTS purchase_orders (
  id           TEXT PRIMARY KEY,
  episode_id   TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  vendor_id    TEXT NOT NULL REFERENCES vendors(id),
  amount       NUMERIC(14,2) NOT NULL,
  description  TEXT,
  created_day  INTEGER NOT NULL,
  status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','fulfilled','closed')),
  origin       TEXT NOT NULL DEFAULT 'sim'
);
CREATE INDEX IF NOT EXISTS po_ep ON purchase_orders(episode_id, vendor_id);

CREATE TABLE IF NOT EXISTS invoices (
  id              TEXT PRIMARY KEY,
  episode_id      TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  vendor_id       TEXT NOT NULL REFERENCES vendors(id),
  po_id           TEXT REFERENCES purchase_orders(id),
  amount          NUMERIC(14,2) NOT NULL,
  invoice_number  TEXT NOT NULL,
  line_items      JSONB NOT NULL DEFAULT '[]',
  received_day    INTEGER NOT NULL,
  due_day         INTEGER NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','matched','approved','paid','rejected','blocked')),
  status_day      INTEGER,
  origin          TEXT NOT NULL DEFAULT 'sim',
  attack_id       TEXT                          -- set when origin='red'; never exposed
);
CREATE INDEX IF NOT EXISTS invoices_ep ON invoices(episode_id, status);
CREATE INDEX IF NOT EXISTS invoices_vendor ON invoices(episode_id, vendor_id);

CREATE TABLE IF NOT EXISTS payments (
  id                 TEXT PRIMARY KEY,
  episode_id         TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  invoice_id         TEXT REFERENCES invoices(id),
  expense_id         TEXT,
  amount             NUMERIC(14,2) NOT NULL,
  to_account         TEXT NOT NULL,
  paid_day           INTEGER NOT NULL,
  paid_by            TEXT NOT NULL,             -- agent
  origin_of_source   TEXT NOT NULL              -- denormalized origin of invoice/expense for scoring
);
CREATE INDEX IF NOT EXISTS payments_ep ON payments(episode_id, paid_day);

CREATE TABLE IF NOT EXISTS expenses (
  id             TEXT PRIMARY KEY,
  episode_id     TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  employee_id    TEXT NOT NULL REFERENCES employees(id),
  amount         NUMERIC(14,2) NOT NULL,
  category       TEXT NOT NULL,
  memo           TEXT,
  submitted_day  INTEGER NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','paid','rejected','blocked')),
  origin         TEXT NOT NULL DEFAULT 'sim',
  attack_id      TEXT
);
CREATE INDEX IF NOT EXISTS expenses_ep ON expenses(episode_id, status);

CREATE TABLE IF NOT EXISTS bank_transactions (
  id                   TEXT PRIMARY KEY,
  episode_id           TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  day                  INTEGER NOT NULL,
  amount               NUMERIC(14,2) NOT NULL,  -- negative = outflow
  counterparty         TEXT,
  memo                 TEXT,
  matched_payment_id   TEXT REFERENCES payments(id)
);
CREATE INDEX IF NOT EXISTS bank_ep ON bank_transactions(episode_id, day);

CREATE TABLE IF NOT EXISTS gl_entries (
  id          TEXT PRIMARY KEY,
  episode_id  TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  day         INTEGER NOT NULL,
  account     TEXT NOT NULL,                    -- e.g. '2000 Accounts Payable'
  debit       NUMERIC(14,2) NOT NULL DEFAULT 0,
  credit      NUMERIC(14,2) NOT NULL DEFAULT 0,
  memo        TEXT,
  posted_by   TEXT NOT NULL,
  ref_type    TEXT,                             -- 'invoice','payment','expense','manual'
  ref_id      TEXT
);
CREATE INDEX IF NOT EXISTS gl_ep ON gl_entries(episode_id, day);

CREATE TABLE IF NOT EXISTS attacks (
  id                TEXT PRIMARY KEY,
  episode_id        TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  scheme_id         TEXT NOT NULL,
  display_name      TEXT NOT NULL,
  story             TEXT NOT NULL,
  day_launched      INTEGER NOT NULL,
  params            JSONB NOT NULL DEFAULT '{}',
  target_amount     NUMERIC(14,2) NOT NULL,
  outcome           TEXT NOT NULL DEFAULT 'pending'
                    CHECK (outcome IN ('pending','extracted','partial','blocked','flagged','failed')),
  amount_extracted  NUMERIC(14,2) NOT NULL DEFAULT 0,
  detected_day      INTEGER,
  notes             TEXT
);
CREATE INDEX IF NOT EXISTS attacks_ep ON attacks(episode_id);

CREATE TABLE IF NOT EXISTS verdicts (
  id                TEXT PRIMARY KEY,
  episode_id        TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  idempotency_key   TEXT NOT NULL,
  day               INTEGER NOT NULL,
  agent             TEXT NOT NULL,              -- whose action was judged (green)
  action            TEXT NOT NULL,              -- e.g. 'invoices.pay'
  entity_type       TEXT,
  entity_id         TEXT,
  amount            NUMERIC(14,2),
  args              JSONB NOT NULL DEFAULT '{}',
  verdict           TEXT NOT NULL CHECK (verdict IN ('allow','block','escalate')),
  reason            TEXT NOT NULL,
  confidence        REAL,
  rules_fired       JSONB NOT NULL DEFAULT '[]',
  enforced          BOOLEAN NOT NULL,           -- false in shadow mode
  latency_ms        INTEGER,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (episode_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS verdicts_ep ON verdicts(episode_id, day);

CREATE TABLE IF NOT EXISTS escalations (
  id           TEXT PRIMARY KEY,
  episode_id   TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  verdict_id   TEXT NOT NULL REFERENCES verdicts(id),
  status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','approved','blocked','timeout')),
  opened_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL,
  resolved_by  TEXT,
  resolved_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS escalations_open ON escalations(episode_id, status);

CREATE TABLE IF NOT EXISTS flags (
  id           TEXT PRIMARY KEY,
  episode_id   TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  day          INTEGER NOT NULL,
  entity_type  TEXT NOT NULL,                   -- 'vendor','invoice','employee','expense','vendor_change'
  entity_id    TEXT NOT NULL,
  severity     TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
  reason       TEXT NOT NULL,
  raised_by    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS flags_ep ON flags(episode_id, entity_type, entity_id);

CREATE TABLE IF NOT EXISTS reports (
  id          TEXT PRIMARY KEY,
  episode_id  TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  day         INTEGER NOT NULL,
  markdown    TEXT NOT NULL,
  posted_by   TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id          BIGSERIAL PRIMARY KEY,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  episode_id  TEXT NOT NULL,
  day         INTEGER NOT NULL,
  agent       TEXT NOT NULL,
  action      TEXT NOT NULL,                    -- route action name
  tool_use_id TEXT,
  args        JSONB NOT NULL DEFAULT '{}',
  result      JSONB NOT NULL DEFAULT '{}',
  http_status INTEGER NOT NULL,
  verdict_id  TEXT
);
CREATE INDEX IF NOT EXISTS audit_ep ON audit_log(episode_id, day);

CREATE TABLE IF NOT EXISTS events (
  id          BIGSERIAL PRIMARY KEY,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  episode_id  TEXT NOT NULL,
  day         INTEGER NOT NULL,
  type        TEXT NOT NULL,
  agent       TEXT,
  payload     JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_ep ON events(episode_id, id);

-- ---------- extension points (core, owned by Ad; see README §16) ----------

-- Per-agent key/value memory across turns. No schema change needed to persist agent state.
CREATE TABLE IF NOT EXISTS agent_state (
  episode_id  TEXT NOT NULL,
  agent       TEXT NOT NULL,
  key         TEXT NOT NULL,
  value       JSONB NOT NULL DEFAULT '{}',
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (episode_id, agent, key)
);

-- Inbox: anything outside the sim (frontend, crowd page, judge) can leave a message for an
-- agent. The orchestrator drains unconsumed rows into `options.inputs` on that agent's next turn.
CREATE TABLE IF NOT EXISTS inputs (
  id            BIGSERIAL PRIMARY KEY,
  episode_id    TEXT NOT NULL,
  target        TEXT NOT NULL CHECK (target IN ('red','green','blue')),
  source        TEXT NOT NULL,                 -- 'frontend', 'crowd', 'judge', extension name
  payload       JSONB NOT NULL DEFAULT '{}',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  consumed_day  INTEGER
);
CREATE INDEX IF NOT EXISTS inputs_pending ON inputs(episode_id, target) WHERE consumed_day IS NULL;

-- Team-owned tables live in contracts/ext/<area>/*.sql and are prefixed <area>_ (red_, green_, blue_, fe_).
