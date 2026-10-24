-- Only sponsor persona IDs, never real consumer identity data or expected decisions.
CREATE TABLE IF NOT EXISTS blue_crs_employee_profiles (
  episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  employee_id TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  persona_id TEXT NOT NULL CHECK (persona_id IN ('P01', 'P12', 'P16')),
  PRIMARY KEY (episode_id, employee_id)
);
