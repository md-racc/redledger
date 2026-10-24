"""Future manual Stage A only. Default refusal is keyless; pytest uses fake SDKs."""

import argparse
import asyncio
import contextlib
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

TOOLS = (
    "ap_queue",
    "approve_expense",
    "approve_invoice",
    "approve_vendor_change",
    "match_invoice",
    "pay_expense",
    "pay_invoice",
    "reject_invoice",
    "reject_vendor_change",
)
CASES = (*TOOLS, "cancel", "granularity", "restriction")
ATTESTATION = "operator-approved-account-cap-or-in-flight-overrun-confirmed"


def failure_codes(e: dict) -> list[str]:
    """Evaluate observations strictly; missing evidence is never a positive receipt."""
    if any(key not in e for key in ("case", "permissions", "preparations", "writes", "calls", "results")):
        return ["evidence_incomplete"]
    codes = []
    for field in ("turn_ok", "listed", "isolated"):
        if e.get(field) is not True:
            codes.append(field + "_unverified")
    credits = e.get("credits")
    if isinstance(credits, bool) or not isinstance(credits, (int, float)) or not math.isfinite(credits) or credits < 0:
        codes.append("usage_unavailable")
    if e.get("error"):
        codes.append(e["error"])
    case = e["case"]
    ps, preps, writes = e["permissions"], e["preparations"], e["writes"]
    calls, results = e["calls"], e["results"]
    if case == "restriction":
        return codes + ["restriction_inconclusive_no_observable_sdk_refusal"]
    if case != "granularity" and e.get("shape") != [(1, 1)]:
        codes.append("unexpected_permission_callback")
    targets = ["pay_invoice", "approve_expense"] if case == "granularity" else ["pay_invoice" if case == "cancel" else case]
    n = len(targets)
    if not len(ps) == len(calls) == len(results) == n:
        codes.append("permission_or_pair_cardinality")
    ids = [p.get("id") for p in ps]
    if len(set(ids)) != n or sorted(p.get("tool", "") for p in ps) != sorted(targets):
        codes.append("unexpected_or_repeated_tool")
    by_call = {call.get("id"): call for call in calls}
    by_result = {result.get("id"): result for result in results}
    if set(by_call) != set(ids) or set(by_result) != set(ids):
        codes.append("event_binding")
    for p in ps:
        call, result = by_call.get(p.get("id"), {}), by_result.get(p.get("id"), {})
        if not p.get("id") or p.get("source") not in {"permission", "stream", "mcp_meta"} or p.get("args_match") is not True:
            codes.append("permission_binding")
        if call != {"id": p.get("id"), "tool": p.get("tool"), "args_match": True} or call.get("args_match") is not True or result.get("id") != p.get("id"):
            codes.append("event_binding")
    blocked = case in ("cancel", "granularity")
    for result in results:
        if result.get("ok") is not (not blocked) or result.get("confirmed") is not (not blocked and case != "ap_queue"):
            codes.append("result_not_confirmed")
        if blocked and result.get("cause") != ("control_hold" if case == "cancel" or not e.get("batch") else "integration_failure"):
            codes.append("cancel_cause")
    for p in ps:
        if p.get("outcome") != ("cancel" if blocked else "proceed_once"):
            codes.append("permission_outcome")
    expected = 0 if case == "ap_queue" or (case == "granularity" and e.get("batch")) else n
    if len(preps) != expected or len(writes) != (0 if blocked else expected):
        codes.append("http_cardinality")
    if expected and {prep.get("id") for prep in preps} != set(ids):
        codes.append("preparation_binding")
    for prep in preps:
        if prep.get("id") not in ids or prep != {"id": prep.get("id"), "binding": True} or prep.get("binding") is not True:
            codes.append("preparation_binding")
    for index, write in enumerate(writes):
        if (
            index >= len(ps)
            or write != {"id": ps[index].get("id"), "binding": True, "verified": True}
            or write.get("verified") is not True
            or write.get("binding") is not True
        ):
            codes.append("write_binding")
    if e.get("mutated") is not (not blocked and case != "ap_queue"):
        codes.append("fixture_mutation_unconfirmed")
    if case == "cancel" and e.get("nonce_delivered") is not True:
        codes.append("cancel_comment_unobserved")
    if case == "granularity":
        shape = e.get("shape")
        if shape != ([(2, 2)] if e.get("batch") else [(1, 1), (1, 1)]):
            codes.append("granularity_unobserved")
    return sorted(set(codes))


async def run_case(case: str) -> dict:
    """Internal runner; callers must pass the CLI approval gates before invoking this."""
    e = {k: [] for k in ("permissions", "preparations", "writes", "calls", "results", "shape")}
    e.update(case=case, turn_ok=False, listed=False, isolated=True, credits=None, mutated=False, nonce_delivered=False, batch=False)
    if case == "restriction":
        # No observable negative-control receipt exists yet. Do not spend on an unqualifiable case.
        return {**e, "passed": False, "failure_codes": ["restriction_inconclusive_no_observable_sdk_refusal"]}
    import httpx
    import respx
    from preparation import preparation_for

    from agent import AP_TOOL_IDS, GreenAgent
    from agentkit import AgentSettings, DroidAgent, TurnRequest
    from agentkit.invocation import current_invocation

    # Reuse the existing fixture implementation without its module-level settings reading .env.
    old = AgentSettings.model_config.get("env_file")
    AgentSettings.model_config["env_file"] = None
    try:
        from conftest import Book, change, expense, invoice
    finally:
        AgentSettings.model_config["env_file"] = old
    book, specs = Book(), {}
    targets = ["pay_invoice", "approve_expense"] if case == "granularity" else ["pay_invoice" if case == "cancel" else case]
    for tool in targets:
        if tool not in TOOLS or tool == "ap_queue":
            specs[tool] = {}
            continue
        action, kind = tool.split("_", 1)
        table = {"invoice": "invoices", "expense": "expenses", "vendor_change": "vendor_changes"}[kind]
        row = {"invoice": invoice, "expense": expense, "vendor_change": change}[kind]("fixture-" + kind)
        if action == "pay":
            row["status"] = "approved"
        args = {"change_id" if kind == "vendor_change" else kind + "_id": row["id"]}
        if action == "match":
            args["po_id"] = row["po_id"] = "fixture-po"
            book.add("purchase_orders", {"id": "fixture-po", "vendor_id": "v", "amount": "1200.00", "created_day": 1, "status": "open"})
        if action == "reject":
            args["reason"] = "explicit fixture rejection"
        book.add(table, row)
        specs[tool] = args
    before = json.dumps(book.rows, sort_keys=True)
    nonce = uuid.uuid4().hex

    def digest(value):
        return hashlib.sha256(str(value).encode()).hexdigest() if value else ""

    class AcceptanceGreen(GreenAgent):
        async def build_prompt(self, req):
            return (
                "Call exactly these tools with these arguments, once each, and no others: "
                + json.dumps(specs)
                + ". Stop afterwards. If canceled, quote the cancellation reason."
            )

        async def on_permission(self, request):
            uses = self.tool_uses(request)
            actions = len(getattr(request, "actions", ()) or ())
            e["shape"].append((actions, len(uses)))
            e["batch"] = e["batch"] or actions > 1 or len(uses) > 1
            start = len(e["permissions"])
            seen = {p["id"] for p in e["permissions"]}
            if not uses or actions != len(uses) or any(u.tool not in specs or u.args != specs[u.tool] or digest(u.tool_use_id) in seen for u in uses):
                e["error"] = "unexpected_permission_callback"
            for u in uses:
                e["permissions"].append({"id": digest(u.tool_use_id), "tool": u.tool, "source": u.source, "args_match": u.args == specs.get(u.tool)})
            if e.get("error"):
                from droid_sdk import ToolConfirmationOutcome

                response = request.respond(ToolConfirmationOutcome.CANCEL, comment="Acceptance harness stopped.")
            else:
                response = await super().on_permission(request)
            for p in e["permissions"][start:]:
                p["outcome"] = getattr(getattr(response, "selected_option", None), "value", getattr(response, "selected_option", None))
            return response

        async def _learn_tool_ids(self, session):
            await super()._learn_tool_ids(session)
            e["listed"] = True

        async def _droid_turn(self, req, emitter):
            assert self.autonomy == "off" and self.identity_policy() == "strict" and self._tool_ids == list(AP_TOOL_IDS)
            async with asyncio.timeout(45):  # Includes opening, listing, one stream, and closing.
                return await DroidAgent._droid_turn(self, req, emitter)

    def intercept(request):
        assert request.url.host == "ledger.invalid" and request.headers["X-Agent"] == "green"
        path = request.url.path.removeprefix("/api/")
        if path == "events":
            for event in json.loads(request.content):
                p = event["payload"]
                if event["type"] == "agent.tool_call":
                    e["calls"].append({"id": digest(p.get("tool_use_id")), "tool": p.get("tool"), "args_match": p.get("args") == specs.get(p.get("tool"))})
                elif event["type"] == "agent.tool_result":
                    try:
                        body = json.loads(p["summary"])
                        reason = json.loads(body.get("reason", "{}"))
                    except (ValueError, TypeError):
                        body, reason = {}, {}
                    e["results"].append(
                        {"id": digest(p.get("tool_use_id")), "ok": p.get("ok"), "confirmed": body.get("outcome") == "confirmed", "cause": reason.get("cause")}
                    )
            return httpx.Response(202, json={"accepted": 1})
        key = digest(request.headers.get("X-Tool-Use-Id"))
        if path == "preparations":
            body = json.loads(request.content)
            # on_permission is still awaiting this response; its observation already exists.
            matching = [p for p in e["permissions"] if p["id"] == key]
            expected = preparation_for(matching[0]["tool"], specs[matching[0]["tool"]]) if len(matching) == 1 else None
            binding = expected is not None and body == expected.model_dump()
            e["preparations"].append({"id": key, "binding": binding})
            assert binding and len(e["preparations"]) <= len(targets)
            return httpx.Response(
                200,
                json={
                    "preparation_id": "synthetic-preparation",
                    "idempotency_key": request.headers["X-Tool-Use-Id"],
                    "controller_mode": "enforce",
                    "day": 3,
                    "action": body["action"],
                    "entity_id": body["entity_id"],
                    "effective": "block" if case in ("cancel", "granularity") else "allow",
                    "decided_by": "gate",
                    "reason": nonce,
                    "expires_at": "2100-01-01T00:00:00Z",
                    "consumed": False,
                },
            )
        if request.method != "GET":
            inv = current_invocation()
            expected = preparation_for(inv.tool, specs.get(inv.tool, {})) if inv else None
            wanted = f"{expected.action.split('.')[0]}/{expected.entity_id}/{expected.action.split('.')[1]}" if expected else None
            body = json.loads(request.content) if request.content else None
            binding = path == wanted and body == (expected.args or None) if expected else False
            e["writes"].append({"id": key, "binding": binding and digest(inv.tool_use_id) == key, "verified": bool(inv and inv.verified)})
            assert case not in ("cancel", "granularity", "restriction") and len(e["writes"]) == 1 and binding
        return book.respond(request)

    settings = AgentSettings(
        _env_file=None,
        AGENT_NAME="green",
        AGENT_TOKEN="synthetic-test-agent",
        DRY_RUN=False,
        BATTLEFIELD_URL="http://ledger.invalid",
        FACTORY_API_KEY=None,
        DROID_MODEL="gemini-3.8-flash",
        DROID_REASONING="low",
        TURN_TIMEOUT_SEC=45,
        HTTP_TIMEOUT_SEC=2,
        GATE_TIMEOUT_SEC=1,
        ESCALATION_TIMEOUT_SEC=1,
        APPROVAL_THRESHOLD="5000",
    )
    try:
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
            router.route(url=re.compile(r"http://ledger\.invalid/api/.*")).mock(side_effect=intercept)
            result = await AcceptanceGreen(settings).run_turn(TurnRequest(episode_id="ep", day=3, controller_mode="enforce"))
        e["turn_ok"] = result.ok is True
        if not e["turn_ok"]:
            e["error"] = "turn_timeout" if result.summary == "turn timed out" else "turn_failed"
        e["credits"] = float(result.usage.factory_credits) if result.usage else None
        if e["credits"] is not None and not math.isfinite(e["credits"]):
            e["credits"] = None
        e["nonce_delivered"] = case == "cancel" and nonce in result.summary
    except Exception:
        e["error"] = "runner_exception"  # Never exception text, types, SDK payloads or secrets.
    e["mutated"] = before != json.dumps(book.rows, sort_keys=True)
    # A changed fixture alone is insufficient: check the expected committed row and payment count.
    if e["mutated"] and case in TOOLS and case != "ap_queue":
        action, kind = case.split("_", 1)
        table = {"invoice": "invoices", "expense": "expenses", "vendor_change": "vendor_changes"}[kind]
        e["mutated"] = book.rows[table]["fixture-" + kind]["status"] == {"match": "matched", "approve": "approved", "reject": "rejected", "pay": "paid"}[
            action
        ] and len(book.rows["payments"]) == int(action == "pay")
    e["failure_codes"] = failure_codes(e)
    e["passed"] = not e["failure_codes"]
    return e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--allow-model-call", action="store_true")
    parser.add_argument("--operator-approval")
    parser.add_argument("--spend-cap-attestation", choices=[ATTESTATION])
    args = parser.parse_args(argv)
    if not args.allow_model_call or not (args.operator_approval or "").strip() or args.spend_cap_attestation != ATTESTATION:
        parser.error("Refused before SDK/auth/settings/network: explicit model permission, operator approval and spend-cap attestation required.")
    print(
        "WARNING: usage is post-hoc, not a hard cap. Externally confirm account cap/overrun approval and track cumulative 16-stream/50,000-credit budget; this process cannot enforce either.",
        file=sys.stderr,
    )
    green = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(green), str(green / "tests"), str(green.parent / "agentkit")]
    os.environ.pop("FACTORY_API_KEY", None)  # CLI authentication only; never inspect the value.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        previous = Path.cwd()
        try:
            with tempfile.TemporaryDirectory(prefix="green-acceptance-") as cwd:
                os.chdir(cwd)
                output = asyncio.run(run_case(args.case))
        except Exception:
            output = {"passed": False, "failure_codes": ["runner_exception"]}
        finally:
            os.chdir(previous)
    print(json.dumps(output, sort_keys=True, allow_nan=False))
    return 0 if output["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
