"""Green's tool surface: the AP workflow. Owner: Dev M.

Every mutating tool is gated by battlefield; a block comes back as {"blocked": true, "reason": ...}
in the tool output, so the model can read why and move on.
"""

from __future__ import annotations

import json

from agentkit import ctx, ledger_tool


@ledger_tool("ap_queue", "List invoices awaiting work (pending/matched/approved), open POs, pending vendor changes, pending expenses, and current flags.")
async def ap_queue() -> str:
    L = ctx.ledger()
    out = {
        "pending": await L.list_invoices(status="pending"),
        "matched": await L.list_invoices(status="matched"),
        "approved": await L.list_invoices(status="approved"),
        "open_pos": await L.list_purchase_orders(status="open"),
        "pending_vendor_changes": await L.list_vendor_changes(status="pending"),
        "pending_expenses": await L.list_expenses(status="pending"),
        "flags": await L.list_flags(),
    }
    return json.dumps(out)


@ledger_tool("vendor_history", "Vendor record plus its paid invoices and POs. Use to sanity-check an invoice before paying.")
async def vendor_history(vendor_id: str) -> str:
    L = ctx.ledger()
    return json.dumps(
        {
            "vendor": await L.get_vendor(vendor_id),
            "paid": await L.list_invoices(status="paid", vendor_id=vendor_id),
            "pos": await L.list_purchase_orders(vendor_id=vendor_id),
        }
    )


@ledger_tool("match_invoice", "Match a pending invoice to a purchase order (three-way match step).")
async def match_invoice(invoice_id: str, po_id: str) -> str:
    return json.dumps(await ctx.ledger().match_invoice(invoice_id, po_id))


@ledger_tool("approve_invoice", "Approve an invoice for payment (no-PO path).")
async def approve_invoice(invoice_id: str) -> str:
    return json.dumps(await ctx.ledger().approve_invoice(invoice_id))


@ledger_tool("reject_invoice", "Reject an invoice with a reason.")
async def reject_invoice(invoice_id: str, reason: str) -> str:
    return json.dumps(await ctx.ledger().reject_invoice(invoice_id, reason))


@ledger_tool("pay_invoice", "Pay a matched/approved invoice. This moves money.")
async def pay_invoice(invoice_id: str) -> str:
    return json.dumps(await ctx.ledger().pay_invoice(invoice_id))


@ledger_tool("approve_vendor_change", "Approve a pending vendor detail change (e.g. bank account).")
async def approve_vendor_change(change_id: str) -> str:
    return json.dumps(await ctx.ledger().approve_vendor_change(change_id))


@ledger_tool("reject_vendor_change", "Reject a pending vendor detail change with a reason.")
async def reject_vendor_change(change_id: str, reason: str) -> str:
    return json.dumps(await ctx.ledger().reject_vendor_change(change_id, reason))


@ledger_tool("approve_expense", "Approve an employee expense.")
async def approve_expense(expense_id: str) -> str:
    return json.dumps(await ctx.ledger().approve_expense(expense_id))


@ledger_tool("pay_expense", "Pay an approved expense. This moves money.")
async def pay_expense(expense_id: str) -> str:
    return json.dumps(await ctx.ledger().pay_expense(expense_id))


@ledger_tool("post_gl", "Post a journal entry: account, debit, credit, memo, ref_type, ref_id.")
async def post_gl(account: str, debit: float = 0.0, credit: float = 0.0, memo: str = "", ref_type: str = "", ref_id: str = "") -> str:
    return json.dumps(
        await ctx.ledger().post_gl_entry(
            {"account": account, "debit": debit, "credit": credit, "memo": memo, "ref_type": ref_type or None, "ref_id": ref_id or None}
        )
    )
