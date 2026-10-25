"""Scheme registry. Owner: Dev Al. Add new schemes here; the catalog and /schemes come from this list."""

from .amount_drift import AmountDrift
from .bank_swap import BankSwap
from .base import SchemeBase
from .duplicate_invoice import DuplicateInvoice
from .expense_inflation import ExpenseInflation
from .ghost_employee import GhostEmployee
from .ghost_vendor import GhostVendor
from .po_mismatch import PoMismatch
from .threshold_split import ThresholdSplit

# Order matters for DRY_RUN: RedAgent.dry_run_turn rotates through this list by day.
SCHEMES: dict[str, SchemeBase] = {
    s.id: s for s in [GhostVendor(), BankSwap(), DuplicateInvoice(), ThresholdSplit(), GhostEmployee(), ExpenseInflation(), PoMismatch(), AmountDrift()]
}

__all__ = ["SCHEMES", "SchemeBase"]
