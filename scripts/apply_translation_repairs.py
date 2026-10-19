#!/usr/bin/env python3
"""Apply reviewed translation repairs in place; without --apply only checks drift.

Pages go through apply_article_repairs.apply and messages through
repair_channel_history.apply_channel, so both refuse to overwrite content that
changed since the plan was prepared and verify the result. Never sends or
deletes messages and never touches checker state in output/.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.notify.telegraph import get_page
from scripts.apply_article_repairs import apply as apply_page
from scripts.audit_channel_history import owned_article_paths
from scripts.prepare_article_repairs import semantic_tree
from scripts.repair_channel_history import apply_channel, verify_snapshot

PLAN = ROOT / "output/channel-review/translation-repairs.json"
RESULTS = ROOT / "output/channel-review/translation-repair-results"


def page_drift(page, token):
    current = get_page(page["path"], token)
    if not current.get("success"):
        return "page unreadable"
    tree = semantic_tree(current["page"]["content"])
    if tree == semantic_tree(page["content"]):
        return "already applied"
    if tree != semantic_tree(page["before_content"]):
        return "page changed since plan"
    return None


def message_drift(message):
    record = RESULTS / (message["post"].replace("/", "-") + ".json")
    if record.exists():
        previous = json.loads(record.read_text())
        if previous.get("ok") and previous.get("sha256") == message["sha256"]:
            return "already applied"
    with requests.Session() as session:
        return verify_snapshot(session, message)


def check(plan, token, owned):
    problems = []
    if plan["status"] != "ready":
        return [f"plan not ready ({', '.join(plan['reasons'])})"]
    if "page" in plan:
        if plan["page"]["path"] not in owned:
            problems.append("page not owned")
        elif drift := page_drift(plan["page"], token):
            problems.append(drift)
    if "message" in plan and (drift := message_drift(plan["message"])):
        problems.append("message: " + drift)
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Edit pages and messages")
    parser.add_argument("--only", nargs="*", help="Target keys, e.g. openclaw_push/128")
    args = parser.parse_args()
    plans = json.loads(PLAN.read_text())["plans"]
    if args.only:
        unknown = set(args.only) - {p["key"] for p in plans}
        if unknown:
            parser.error("unknown target: " + ", ".join(sorted(unknown)))
        plans = [p for p in plans if p["key"] in args.only]

    config = dotenv_values(ROOT / ".env")
    token = config["TELEGRAPH_ACCESS_TOKEN"]
    owned = owned_article_paths(token)

    blocked = False
    for plan in plans:
        parts = (["page"] if "page" in plan else []) + (["message"] if "message" in plan else [])
        problems = check(plan, token, owned)
        # Already-applied parts are fine; anything else blocks the target.
        blocking = [p for p in problems if not p.endswith("already applied")]
        blocked |= bool(blocking)
        status = "BLOCKED " + "; ".join(blocking) if blocking else "OK"
        print(f"{plan['key']:22s} {plan['title']} {plan['version']:10s} [{'+'.join(parts)}] {status}", flush=True)
    if blocked:
        raise SystemExit("Refusing to continue: resolve blocked targets or narrow --only")
    if not args.apply:
        print("Check only; rerun with --apply to edit.")
        return

    RESULTS.mkdir(parents=True, exist_ok=True)
    failures = 0
    for plan in plans:
        if "page" in plan:
            if not apply_page(plan["page"], token, owned, RESULTS)["ok"]:
                # The message links the page; never announce an unrepaired page.
                failures += 1
                continue
        if "message" in plan:
            result = apply_channel([plan["message"]], config, RESULTS)[0]
            failures += not result["ok"]
            print(f"{'OK' if result['ok'] else 'FAIL'} {plan['message']['post']}"
                  + (f": {result['error']}" if result.get("error") else ""), flush=True)
    print(f"Repaired: {len(plans) - failures}/{len(plans)}", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
