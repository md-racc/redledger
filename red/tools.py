"""Red's tool surface as seen by its Droid session. Owner: Dev Al.

Thin wrappers over LedgerClient (red routes only). Keep tool descriptions crisp: the model reads
them. Every tool returns JSON text. The @ledger_tool wrapper emits tool_call/tool_result events
and converts ledger errors into readable tool output.
"""

from __future__ import annotations

import json

from evolution import RATIONALE, fold, lineage_info, view

from agentkit import ctx, ledger_tool
from schemes import SCHEMES


@ledger_tool("list_schemes", "List the fraud schemes available, with id, story and expected impact.")
async def list_schemes() -> str:
    return json.dumps([s.catalog().model_dump() for s in SCHEMES.values()])


@ledger_tool("inspect_books", "Summarize the current ledger: vendors, open invoices, recent payments, pending vendor changes. Use before choosing a scheme.")
async def inspect_books() -> str:
    L = ctx.ledger()
    vendors = await L.list_vendors(status="active")
    pending = await L.list_invoices(status="pending")
    paid = await L.list_invoices(status="paid")
    changes = await L.list_vendor_changes(status="pending")
    learned = {}
    req = ctx.turn()
    info = lineage_info(req.options)
    if info is not None:
        try:
            playbook = await L.get_playbook()
            content = (playbook or {}).get("content") or {}
            debrief = req.options.get("debrief")
            items = debrief.get("items") if isinstance(debrief, dict) else None
            updated = fold(content, items, info.generation, req.episode_id)
            if updated is not None and playbook is not None:
                # The decorator owns this invocation; LedgerClient supplies its current write key.
                await L.put_playbook(updated, RATIONALE, playbook.get("version", 0))
            learned["lineage"] = view(updated if updated is not None else content, req.day)
        except Exception as e:  # learning is optional: any failure (HTTP status, timeout, bad shape) keeps the books and the attack
            learned["lineage"] = {"error": getattr(e, "status", None) or type(e).__name__}
    return json.dumps(
        {
            **learned,
            "active_vendors": len(vendors),
            "vendors_sample": [{"id": v["id"], "name": v["name"], "category": v["category"], "created_day": v["created_day"]} for v in vendors[:15]],
            "pending_invoices": [{"id": i["id"], "vendor_id": i["vendor_id"], "amount": i["amount"], "po_id": i.get("po_id")} for i in pending[:20]],
            "recent_paid": [{"id": i["id"], "vendor_id": i["vendor_id"], "amount": i["amount"], "invoice_number": i["invoice_number"]} for i in paid[-10:]],
            "pending_vendor_changes": len(changes),
        }
    )


@ledger_tool("run_scheme", "Declare and execute a fraud scheme by id with optional params (JSON object as string). Returns a summary.")
async def run_scheme(scheme_id: str, params_json: str = "{}") -> str:
    L = ctx.ledger()
    scheme = SCHEMES.get(scheme_id)
    if not scheme:
        return json.dumps({"error": f"unknown scheme {scheme_id}", "available": list(SCHEMES)})
    params = json.loads(params_json or "{}")
    if not await scheme.viable(L):
        return json.dumps({"error": f"{scheme_id} not viable against current books"})
    plan = await scheme.plan(L, params)
    atk = await L.declare_attack(scheme.attack_decl(plan, params))
    summary = await scheme.execute(L, plan)
    return json.dumps({"attack_id": atk["id"], "summary": summary})


@ledger_tool("create_vendor", "Create a new vendor record. Fields: name, bank_account, bank_routing, ein?, address?, category?")
async def create_vendor(name: str, bank_account: str, bank_routing: str, ein: str = "", address: str = "", category: str = "") -> str:
    return json.dumps(
        await ctx.ledger().create_vendor(
            {
                "name": name,
                "bank_account": bank_account,
                "bank_routing": bank_routing,
                "ein": ein or None,
                "address": address or None,
                "category": category or None,
            }
        )
    )


@ledger_tool("submit_invoice", "Submit an invoice from a vendor. po_id optional.")
async def submit_invoice(vendor_id: str, amount: float, invoice_number: str, po_id: str = "") -> str:
    return json.dumps(await ctx.ledger().submit_invoice({"vendor_id": vendor_id, "amount": amount, "invoice_number": invoice_number, "po_id": po_id or None}))


@ledger_tool("request_vendor_bank_change", "Request that a vendor's bank account be changed, with a plausible justification.")
async def request_vendor_bank_change(vendor_id: str, new_account: str, justification: str) -> str:
    return json.dumps(
        await ctx.ledger().request_vendor_change({"vendor_id": vendor_id, "field": "bank_account", "new_value": new_account, "justification": justification})
    )


@ledger_tool("submit_expense", "Submit an expense reimbursement for an employee.")
async def submit_expense(employee_id: str, amount: float, category: str, memo: str = "") -> str:
    return json.dumps(await ctx.ledger().submit_expense({"employee_id": employee_id, "amount": amount, "category": category, "memo": memo}))


@ledger_tool("add_employee", "Add an employee/contractor to payroll.")
async def add_employee(name: str, role: str, salary: float, bank_account: str) -> str:
    return json.dumps(await ctx.ledger().create_employee({"name": name, "role": role, "salary": salary, "bank_account": bank_account}))
