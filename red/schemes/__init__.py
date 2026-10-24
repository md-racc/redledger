"""Scheme registry. Owner: Dev Al. Add new schemes here; the catalog and /schemes come from this list."""

from .bank_swap import BankSwap
from .base import SchemeBase
from .duplicate_invoice import DuplicateInvoice
from .ghost_employee import GhostEmployee
from .ghost_vendor import GhostVendor
from .threshold_split import ThresholdSplit

# Order matters for DRY_RUN: RedAgent.dry_run_turn rotates through this list by day.
SCHEMES: dict[str, SchemeBase] = {s.id: s for s in [GhostVendor(), BankSwap(), DuplicateInvoice(), ThresholdSplit(), GhostEmployee()]}

# Planned (README §8): expense_inflation, po_mismatch, amount_drift. One file each, registered above.

__all__ = ["SCHEMES", "SchemeBase"]
