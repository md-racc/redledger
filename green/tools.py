"""Small decorated AP surface shared by deterministic and eventual live turns.

Shared agentkit carries one invocation ID across tool events and ledger write headers.
Live SDK acceptance and the canonical gate preflight remain separate prerequisites.
"""

from __future__ import annotations

from workflow import operation, queue

from agentkit import ledger_tool


@ledger_tool("ap_queue", "List pending vendor changes, pending/matched/approved invoices, open POs and pending/approved expenses.")
async def ap_queue() -> str:
    return await queue()


@ledger_tool("match_invoice", "Match a pending invoice only to its referenced open PO for that vendor.")
async def match_invoice(invoice_id: str, po_id: str) -> str:
    return await operation("match", "invoice", invoice_id, po_id=po_id)


@ledger_tool("approve_invoice", "Approve a pending genuine no-PO invoice within the inclusive auto-approval limit.")
async def approve_invoice(invoice_id: str) -> str:
    return await operation("approve", "invoice", invoice_id)


@ledger_tool("reject_invoice", "Reject an invoice with an explicit reason; never retry a blocked entity.")
async def reject_invoice(invoice_id: str, reason: str) -> str:
    return await operation("reject", "invoice", invoice_id, reason=reason)


@ledger_tool("pay_invoice", "Pay a current matched/approved invoice within the inclusive auto-approval limit.")
async def pay_invoice(invoice_id: str) -> str:
    return await operation("pay", "invoice", invoice_id)


@ledger_tool("approve_vendor_change", "Approve a pending vendor detail change procedurally, without investigation.")
async def approve_vendor_change(change_id: str) -> str:
    return await operation("approve", "vendor_change", change_id)


@ledger_tool("reject_vendor_change", "Reject a pending vendor detail change with an explicit reason.")
async def reject_vendor_change(change_id: str, reason: str) -> str:
    return await operation("reject", "vendor_change", change_id, reason=reason)


@ledger_tool("approve_expense", "Approve a pending employee expense. The invoice threshold does not apply.")
async def approve_expense(expense_id: str) -> str:
    return await operation("approve", "expense", expense_id)


@ledger_tool("pay_expense", "Pay a current approved expense, including backlog. No invoice threshold applies.")
async def pay_expense(expense_id: str) -> str:
    return await operation("pay", "expense", expense_id)
