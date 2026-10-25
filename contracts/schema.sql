-- Red Ledger canonical schema. Applied by battlefield at startup (idempotent).
-- Change this file ONLY via a contracts/ PR with a CHANGELOG entry.
-- Conventions: text ids with prefixes (ep_, ven_, inv_, ...), integer "day" = simulated business day
-- within an episode (0-based), money as NUMERIC(14,2), timestamps UTC.
-- `origin` is provenance for scoring: 'sim' (seeded/legit), 'red', 'green', 'blue'.
-- Battlefield NEVER returns `origin` to any X-Agent caller.

-- A lineage is a chain of episodes, one per generation, whose agents carry versioned playbooks
-- from one generation to the next (ARCHITECTURE.md, Evolution). `config` is validated by battlefield
-- (LineageConfig in agentkit/models.py). Generation g runs on seed `base_seed + g`; no two episodes
-- of a lineage share a seed (episodes_lineage_seed below), so the legit traffic agents learn about in
-- one generation is never replayed verbatim in the next.
CREATE TABLE IF NOT EXISTS lineages (
  id                  TEXT PRIMARY KEY,
  name                TEXT NOT NULL DEFAULT '',
  base_seed           INTEGER NOT NULL,
  config              JSONB NOT NULL,
  status              TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created','running','paused','finished','failed')),
  current_generation  INTEGER NOT NULL DEFAULT 0,   -- last generation created (0 = none yet)
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS episodes (
  id               TEXT PRIMARY KEY,
  seed             INTEGER NOT NULL,
  controller_mode  TEXT NOT NULL CHECK (controller_mode IN ('off','shadow','enforce')),
  days             INTEGER NOT NULL DEFAULT 10,
  status           TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created','running','paused','finished','failed')),
  current_day      INTEGER NOT NULL DEFAULT 0,
  attack_plan      JSONB,                       -- optional forced schedule: [{day, scheme_id, params}]
  lineage_id       TEXT REFERENCES lineages(id), -- NULL = a plain episode: nothing is ever revealed to its agents
  generation       INTEGER,                      -- set iff lineage_id is set; 1-based
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
  origin         TEXT NOT NULL DEFAULT 'sim',
  attack_id      TEXT                           -- set when origin='red'; never exposed
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
  notes             TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),  -- orders a day's attacks for attack_id linking
  -- First day the attack is resolved: outcome 'failed', or it has entities and none is pending.
  -- Only resolved attacks may be revealed to agents mid-episode (lineage episodes only).
  resolved_day      INTEGER,
  -- Day a debrief first revealed it. Once set, battlefield stops re-resolving the attack: outcome,
  -- amount_extracted and detected_day are frozen, so hindsight after the reveal never scores as detection.
  revealed_day      INTEGER
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
  cause             TEXT CHECK (cause IN ('control','gate_unavailable')),  -- NULL on rows older than the column
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

-- Green's gated actions prepared before they run (ledger-api.yaml POST /preparations). One row per
-- episode + idempotency key (the SDK tool_use_id), in every mode (off rows have no verdict). The
-- verdict row records what blue said; this row records what execution under the key may do.
-- expires_at = created_at + 120 s, never extended. The gated route consumes the row in its own
-- transaction (CAS on consumed_at IS NULL). state_hash = sha256 of the action's narrow fingerprint.
CREATE TABLE IF NOT EXISTS preparations (
  id               TEXT PRIMARY KEY,                          -- prep_
  episode_id       TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  idempotency_key  TEXT NOT NULL,
  day              INTEGER NOT NULL,
  agent            TEXT NOT NULL,
  controller_mode  TEXT NOT NULL CHECK (controller_mode IN ('off','shadow','enforce')),
  action           TEXT NOT NULL,
  entity_type      TEXT,
  entity_id        TEXT,
  amount           NUMERIC(14,2),
  args             JSONB NOT NULL DEFAULT '{}',
  state_hash       TEXT NOT NULL,
  verdict_id       TEXT REFERENCES verdicts(id),              -- NULL in off
  escalation_id    TEXT REFERENCES escalations(id),
  effective        TEXT NOT NULL CHECK (effective IN ('allow','block','pending')),
  decided_by       TEXT CHECK (decided_by IN ('mode','gate','human','timeout')),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at       TIMESTAMPTZ,
  expires_at       TIMESTAMPTZ NOT NULL,
  consumed_at      TIMESTAMPTZ,
  consumed_status  INTEGER,
  UNIQUE (episode_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS preparations_pending ON preparations(episode_id) WHERE effective = 'pending';

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

-- events and audit_log are keyed by (id, ts), not id alone: Timescale (optional image swap,
-- AGENTS.md §4) partitions hypertables on ts and requires it in every unique index. id stays a
-- unique-in-practice BIGSERIAL with its own index for `after_id` cursors. Battlefield's startup
-- turns both into hypertables only when the timescaledb extension is available (guarded: a plain
-- postgres:16 keeps ordinary tables).
CREATE TABLE IF NOT EXISTS audit_log (
  id          BIGSERIAL,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  episode_id  TEXT NOT NULL,
  day         INTEGER NOT NULL,
  agent       TEXT NOT NULL,
  action      TEXT NOT NULL,                    -- route action name
  tool_use_id TEXT,
  args        JSONB NOT NULL DEFAULT '{}',
  result      JSONB NOT NULL DEFAULT '{}',
  http_status INTEGER NOT NULL,
  verdict_id  TEXT,
  PRIMARY KEY (id, ts)
);
CREATE INDEX IF NOT EXISTS audit_ep ON audit_log(episode_id, day);
CREATE INDEX IF NOT EXISTS audit_id ON audit_log(id);

CREATE TABLE IF NOT EXISTS events (
  id          BIGSERIAL,
  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
  episode_id  TEXT NOT NULL,
  day         INTEGER NOT NULL,
  type        TEXT NOT NULL,
  agent       TEXT,
  payload     JSONB NOT NULL DEFAULT '{}',
  PRIMARY KEY (id, ts)
);
CREATE INDEX IF NOT EXISTS events_ep ON events(episode_id, id);
CREATE INDEX IF NOT EXISTS events_id ON events(id);

-- ---------- evolution (lineages; ARCHITECTURE.md, Evolution) ----------

-- Per (lineage, agent) versioned playbook. Content is opaque to battlefield and owned by the agent's
-- team. Versions are immutable; version 0 is the seed ({}), every write adds one. Agents read and
-- write only their own. Diffs between versions are computed at read time, never stored.
CREATE TABLE IF NOT EXISTS playbooks (
  id              BIGSERIAL PRIMARY KEY,
  lineage_id      TEXT NOT NULL REFERENCES lineages(id) ON DELETE CASCADE,
  agent           TEXT NOT NULL CHECK (agent IN ('red','green','blue')),
  version         INTEGER NOT NULL,
  parent_version  INTEGER,                      -- NULL only for version 0
  generation      INTEGER NOT NULL,             -- generation it was written in (reflect: the one reflected on; seed: 0)
  episode_id      TEXT,                         -- NULL for seed/operator
  day             INTEGER,                      -- set for source 'turn' only
  source          TEXT NOT NULL CHECK (source IN ('seed','turn','reflect','operator')),
  content         JSONB NOT NULL CHECK (octet_length(content::text) <= 65536),
  rationale       TEXT NOT NULL DEFAULT '',
  tool_use_id     TEXT,                         -- X-Tool-Use-Id of a 'turn' write; a retry returns the same version
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (lineage_id, agent, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS playbooks_tool_use ON playbooks(lineage_id, agent, tool_use_id) WHERE tool_use_id IS NOT NULL;

-- Every disclosure of ground truth to an agent: daily debriefs (day set) and after-action reviews
-- between generations (day NULL). `payload` is exactly what the agent was shown.
CREATE TABLE IF NOT EXISTS debriefs (
  id          BIGSERIAL PRIMARY KEY,
  lineage_id  TEXT NOT NULL REFERENCES lineages(id) ON DELETE CASCADE,
  generation  INTEGER NOT NULL,
  episode_id  TEXT NOT NULL,
  day         INTEGER,                          -- NULL = after-action review
  agent       TEXT NOT NULL CHECK (agent IN ('red','green','blue')),
  payload     JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS debriefs_lineage ON debriefs(lineage_id, generation, agent);
CREATE INDEX IF NOT EXISTS debriefs_ep ON debriefs(episode_id, day);

-- ---------- extension points (core, owned by Ad; see README.md, Ledger API overview: extensions) ----------

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

-- ---------- additive upgrades for databases created by an older version of this file ----------
-- CREATE TABLE IF NOT EXISTS never adds columns to an existing table, so every column added to a
-- table above after the initial contracts also gets an idempotent ALTER here. No `make db-reset`.

-- 2026-10-24: attacks.created_at (existing rows get the upgrade time; ties fall back to id),
-- vendor_changes.attack_id (existing rows stay NULL; scoring falls back to its same-day heuristic).
ALTER TABLE attacks ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE vendor_changes ADD COLUMN IF NOT EXISTS attack_id TEXT;
CREATE INDEX IF NOT EXISTS vendor_changes_attack ON vendor_changes(attack_id) WHERE attack_id IS NOT NULL;

-- 2026-10-24: lineages (evolution). episodes.lineage_id/generation (existing rows stay NULL = plain
-- episodes), attacks.resolved_day/revealed_day (existing rows stay NULL = never revealed).
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS lineage_id TEXT REFERENCES lineages(id);
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS generation INTEGER;
ALTER TABLE attacks ADD COLUMN IF NOT EXISTS resolved_day INTEGER;
ALTER TABLE attacks ADD COLUMN IF NOT EXISTS revealed_day INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS episodes_lineage_gen ON episodes(lineage_id, generation) WHERE lineage_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS episodes_lineage_seed ON episodes(lineage_id, seed) WHERE lineage_id IS NOT NULL;

-- 2026-10-24: verdicts.cause (gate preparations). Existing rows stay NULL = unknown; read them as
-- 'control' unless rules_fired contains 'gate_timeout'.
ALTER TABLE verdicts ADD COLUMN IF NOT EXISTS cause TEXT CHECK (cause IN ('control','gate_unavailable'));

-- 2026-10-24: events and audit_log primary keys (id) -> (id, ts), for Timescale hypertables (see the
-- comment above audit_log). Only rewrites a primary key that is exactly (id); a no-op on re-apply and
-- on databases created by this file. Nothing references either table by foreign key.
DO $$
DECLARE t text; c text;
BEGIN
  FOREACH t IN ARRAY ARRAY['events', 'audit_log'] LOOP
    SELECT con.conname INTO c
      FROM pg_constraint con
     WHERE con.conrelid = t::regclass AND con.contype = 'p'
       AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
              FROM unnest(con.conkey) AS k(n)
              JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.n) = ARRAY['id'];
    IF c IS NOT NULL THEN
      EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', t, c);
      EXECUTE format('ALTER TABLE %I ADD PRIMARY KEY (id, ts)', t);
    END IF;
  END LOOP;
END $$;
