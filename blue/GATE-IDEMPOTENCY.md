# Gate action binding

Blue binds each episode/key to its first admitted action, including while its verdict is
pending. This implements the action-binding rule added in contracts PR #33.

- Action, entity type, entity ID, and amount must match. A sub-cent amount difference is
  tolerated; a full cent is a conflict. The comparison remains anchored to the first amount.
- For `gl.post`, posted fields replace the generated entity ID. JSON field order and equivalent
  numeric encodings do not change the action; a boolean is not a monetary number.
- Richer context, a later day, or a controller-mode change does not change the action or repair
  an earlier decision. An unchanged action replays the complete first verdict for 120 seconds.
- A conflicting `/gate` request returns HTTP 409 with
  `{"detail":"idempotency key reused for a different action"}`. It does not join pending work,
  invoke the advisory provider, replace the original binding, or borrow the earlier verdict.

Bindings expire with their verdicts and share their cache generations. Admission failures and
failed computations do not leave an action reserved. Existing capacity limits, cancellation
shielding, episode isolation, and retention beyond 5,000 entries remain in place.

This is process-local Blue protection, not durable or distributed idempotency. Battlefield
remains the enforcement and audit point; its contract-defined conflict response includes the
stored verdict ID. Blue neither creates that ID nor mutates the ledger from `/gate`.
