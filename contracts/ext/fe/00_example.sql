-- fe_ example table backing battlefield/extensions/fe_example.py. Delete with it.
CREATE TABLE IF NOT EXISTS fe_example_nudges (
  id          BIGSERIAL PRIMARY KEY,
  episode_id  TEXT NOT NULL,
  target      TEXT NOT NULL,
  who         TEXT NOT NULL,
  message     TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
