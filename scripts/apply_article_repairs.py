#!/usr/bin/env python3
"""Apply reviewed Telegraph plans to owned existing pages, with read-back checks."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.notify.telegraph import edit_page, get_page, html_to_nodes
from scripts.audit_channel_history import owned_article_paths
from scripts.prepare_article_repairs import semantic_tree


def apply(plan, token, owned, directory):
    path = plan["path"]
    digest = hashlib.sha256(json.dumps([plan["title"], plan["content"]], ensure_ascii=False).encode()).hexdigest()
    record_path = directory / (path + ".json")
    previous = {}
    if record_path.exists():
        previous = json.loads(record_path.read_text())
        if previous.get("ok") and previous.get("sha256") == digest:
            return previous
    result = {"path": path, "sha256": digest, "ok": False}
    if path not in owned:
        result["error"] = "Page not owned by configured Telegraph account"
    elif any(v is False for v in plan["checks"].values()):
        result["error"] = "Plan failed content-preservation checks"
    elif html_to_nodes(plan["content_html"]) != plan["content"]:
        result["error"] = "Planned HTML and nodes do not match"
    else:
        current = get_page(path, token)
        if not current.get("success"):
            result["error"] = "Pre-edit read failed"
        elif semantic_tree(current["page"]["content"]) not in (
            semantic_tree(plan["before_content"]), semantic_tree(plan["content"]),
            semantic_tree((previous.get("after") or {}).get("content", [])),
        ):
            result["error"] = "Page changed since snapshot; refusing to overwrite"
        else:
            page = current["page"]
            result["before"] = page
            # Persist recovery data before mutation.
            record_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            edited = edit_page(path, plan["title"], plan["content_html"], token,
                               author_name=page.get("author_name"), author_url=page.get("author_url"))
            if not edited.get("success"):
                result["error"] = edited.get("error", "Edit rejected")
            else:
                verified = get_page(path, token)
                result["ok"] = bool(verified.get("success") and semantic_tree(verified["page"].get("content", [])) == semantic_tree(plan["content"])
                                    and verified["page"].get("title") == plan["title"])
                result["after"] = verified.get("page")
                if not result["ok"]:
                    result["error"] = "Read-back mismatch"
    record_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(("OK " if result["ok"] else "FAIL ") + path + (": " + result["error"] if result.get("error") else ""), flush=True)
    time.sleep(0.5)
    return result


def main():
    directory = ROOT / "output/channel-review"
    plans = json.loads((directory / "article-repairs.json").read_text())["plans"]
    token = dotenv_values(ROOT / ".env")["TELEGRAPH_ACCESS_TOKEN"]
    owned = owned_article_paths(token)
    result_dir = directory / "article-results"
    result_dir.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: apply(p, token, owned, result_dir), plans))
    print(f"Verified existing-page edits: {sum(r['ok'] for r in results)}/{len(results)}", flush=True)
    if not all(r["ok"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
