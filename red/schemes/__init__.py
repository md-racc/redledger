"""Scheme registry. Owner: Dev Al. Add new schemes here; the catalog and /schemes come from this list."""

from .base import SchemeBase
from .ghost_vendor import GhostVendor

SCHEMES: dict[str, SchemeBase] = {s.id: s for s in [GhostVendor()]}

# Planned (README §8): bank_swap, duplicate_invoice, threshold_split, ghost_employee,
# expense_inflation, po_mismatch, amount_drift. One file each, registered above.

__all__ = ["SCHEMES", "SchemeBase"]
