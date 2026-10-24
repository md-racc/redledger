"""Scheme registry. Owner: Dev Al. Add new schemes here; the catalog and /schemes come from this list."""

from .bank_swap import BankSwap
from .base import SchemeBase
from .duplicate_invoice import DuplicateInvoice
from .ghost_vendor import GhostVendor

SCHEMES: dict[str, SchemeBase] = {s.id: s for s in [GhostVendor(), BankSwap(), DuplicateInvoice()]}

# Planned (README §8): threshold_split, ghost_employee (in flight on red/schemes-split-ghost),
# expense_inflation, po_mismatch, amount_drift. One file each, registered above.

__all__ = ["SCHEMES", "SchemeBase"]
