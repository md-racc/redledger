"""Live smoke for the human-in-the-loop escalation path, driven through the operator API only.

Needs a running stack: battlefield + mock red/green/blue, with mock blue started with
MOCK_BLUE_ESCALATE set (e.g. `amount>3000`) and battlefield with a small ESCALATION_TIMEOUT_SEC.
It creates an `enforce` episode, steps it day by day, and while green's gated calls are held it
resolves the open escalations by plan (default: approve the 1st, block the 2nd, let the 3rd time
out, approve the rest), then checks events, escalation rows, audit rows, entity status, the
frontend views and the resolve edge cases (409s). Exit status 0 = every check passed.

    BF_URL=http://localhost:8800 OPERATOR_TOKEN=... uv run python scripts/escalation_smoke.py --days 2
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime
from typing import Any

import httpx

FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  [{'ok' if ok else 'FAIL'}] {what}")
    if not ok:
        FAILS.append(what)


async def resolver(cl: httpx.AsyncClient, ep: str, plan: list[str], rest: str, seen: dict[str, dict[str, Any]], stop: asyncio.Event) -> None:
    """Poll the open queue; decide each new escalation once, by plan order."""
    while not stop.is_set():
        r = await cl.get("/api/escalations", params={"episode_id": ep, "status": "open"})
        r.raise_for_status()
        for esc in sorted(r.json(), key=lambda e: e["opened_at"]):
            if esc["id"] in seen:
                continue
            n = len(seen)
            decision = plan[n] if n < len(plan) else rest
            seen[esc["id"]] = {**esc, "plan": decision, "t_seen": time.monotonic()}
            print(f"  escalation #{n + 1} {esc['id']} {esc['action']} {esc['entity_type']}:{esc['entity_id']} ${float(esc['amount'] or 0):,.2f} -> {decision}")
            if decision in ("approve", "block"):
                rr = await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": decision, "by": "smoke-judge"})
                seen[esc["id"]]["resolve_status"] = rr.status_code
        await asyncio.sleep(0.1)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--plan", default="approve,block,timeout", help="decisions for the first escalations, in order")
    ap.add_argument("--rest", default="approve", choices=["approve", "block", "timeout"])
    args = ap.parse_args()
    base = os.environ.get("BF_URL", "http://localhost:8000")
    token = os.environ.get("OPERATOR_TOKEN", "change-me")
    plan = [p.strip() for p in args.plan.split(",") if p.strip()]

    async with httpx.AsyncClient(base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=httpx.Timeout(30, read=900)) as cl:
        health = (await cl.get("/api/health")).json()
        print("health:", {a: (h.get("ok"), h.get("model")) for a, h in health["agents"].items()})
        ep = (await cl.post("/api/episodes", json={"seed": args.seed, "controller_mode": "enforce", "days": args.days, "name": "escalation-smoke"})).json()
        eid = ep["id"]
        print(f"episode {eid} enforce days={args.days} seed={args.seed}")

        seen: dict[str, dict[str, Any]] = {}
        stop = asyncio.Event()
        task = asyncio.create_task(resolver(cl, eid, plan, args.rest, seen, stop))
        try:
            for d in range(args.days):
                t0 = time.monotonic()
                r = await cl.post(f"/api/episodes/{eid}/step")
                print(f"day {d}: step {r.status_code} in {time.monotonic() - t0:.1f}s; score {r.json().get('score')}")
        finally:
            stop.set()
            await task

        print("checks:")
        rows = {e["id"]: e for e in (await cl.get("/api/escalations", params={"episode_id": eid, "status": "all"})).json()}
        events = (await cl.get("/api/events", params={"episode_id": eid, "limit": 5000})).json()
        audit = (await cl.get("/api/audit_log", params={"episode_id": eid, "limit": 5000})).json()
        fe = {e["id"]: e for e in (await cl.get(f"/api/fe/episodes/{eid}/escalations")).json()}
        opened = {e["payload"]["escalation_id"]: e for e in events if e["type"] == "escalation.opened"}
        resolved = {e["payload"]["escalation_id"]: e for e in events if e["type"] == "escalation.resolved"}
        mutations = {e["payload"].get("verdict_id"): e for e in events if e["type"] == "ledger.mutation"}

        check(len(seen) >= len(plan), f"at least {len(plan)} escalations opened (saw {len(seen)})")
        check(set(rows) == set(seen) == set(opened) == set(resolved), "every escalation has a row, an opened and a resolved event")
        check(not [e for e in rows.values() if e["status"] == "open"], "nothing left open")
        want_status = {"approve": "approved", "block": "blocked", "timeout": "timeout"}
        want_http = {"approve": {200, 201}, "block": {403}, "timeout": {403}}
        for i, (esc_id, s) in enumerate(sorted(seen.items(), key=lambda kv: kv[1]["t_seen"]), 1):
            row, op, res = rows.get(esc_id, {}), opened.get(esc_id), resolved.get(esc_id)
            dec = s["plan"]
            tag = f"#{i} {esc_id} ({dec})"
            check(row.get("status") == want_status[dec], f"{tag}: row status {row.get('status')}")
            check(bool(op and res and op["id"] < res["id"]), f"{tag}: opened before resolved")
            if res:
                by = "system" if dec == "timeout" else "smoke-judge"
                check(res["payload"]["decision"] == dec and res["payload"]["by"] == by, f"{tag}: resolved payload {res['payload']}")
            if op:
                p = op["payload"]
                check(
                    all(p.get(k) is not None for k in ("verdict_id", "action", "reason", "expires_at")),
                    f"{tag}: opened payload has verdict/action/reason/expires_at",
                )
            if dec in ("approve", "block"):
                check(s.get("resolve_status") == 200, f"{tag}: resolve returned {s.get('resolve_status')}")
            held = [a for a in audit if a.get("verdict_id") == s["verdict_id"]]
            check(len(held) == 1 and held[0]["http_status"] in want_http[dec], f"{tag}: green's held call answered {[a['http_status'] for a in held]}")
            check((s["verdict_id"] in mutations) == (dec == "approve"), f"{tag}: ledger.mutation {'present' if dec == 'approve' else 'absent'}")
            if s["entity_type"] in ("invoice", "vendor_change", "expense"):
                trail = (await cl.get(f"/api/fe/episodes/{eid}/entities/{s['entity_type']}/{s['entity_id']}")).json()
                st = trail["entity"]["status"]
                check((st == "blocked") == (dec != "approve"), f"{tag}: {s['entity_type']} status {st}")
            f = fe.get(esc_id, {})
            check(f.get("amount") is not None or s["entity_type"] == "vendor_change", f"{tag}: fe view has amount/reason/expires_at={f.get('expires_at')}")
            if dec == "timeout" and op and res:
                dt = (datetime.fromisoformat(res["ts"]) - datetime.fromisoformat(op["ts"])).total_seconds()
                print(f"    timed out after {dt:.1f}s")

        # edge cases on the operator API
        any_id = next(iter(seen), None)
        if any_id:
            r = await cl.post(f"/api/escalations/{any_id}/resolve", json={"decision": "approve", "by": "smoke-judge"})
            check(r.status_code == 409, f"resolving a finished escalation again -> {r.status_code}")
        timed = next((k for k, v in seen.items() if v["plan"] == "timeout"), None)
        if timed:
            r = await cl.post(f"/api/escalations/{timed}/resolve", json={"decision": "approve", "by": "smoke-judge"})
            check(r.status_code == 409, f"resolving after timeout -> {r.status_code}")
        r = await cl.post("/api/escalations/esc_does_not_exist/resolve", json={"decision": "approve"})
        check(r.status_code in (404, 409), f"resolving an unknown id -> {r.status_code}")
        r = await cl.post(f"/api/escalations/{any_id or 'x'}/resolve", json={"decision": "maybe"})
        check(r.status_code == 422, f"bad decision -> {r.status_code}")

        sc = (await cl.get(f"/api/episodes/{eid}/score")).json()
        attacks = (await cl.get("/api/attacks/all", params={"episode_id": eid})).json()
        snap = (await cl.get(f"/api/fe/episodes/{eid}/snapshot")).json()
        print("score:", sc)
        print("attacks:", [(a["scheme_id"], a["outcome"], float(a["amount_extracted"]), a["detected_day"]) for a in attacks])
        print("snapshot open_escalations:", snap["controls"]["open_escalations"])
        print("episode:", eid)
    print(f"{'PASS' if not FAILS else 'FAIL'}: {len(FAILS)} failed checks")
    for x in FAILS:
        print("  -", x)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
