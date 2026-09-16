#!/usr/bin/env python3
"""Read-only acceptance checks for stored and publicly readable Telegraph repairs."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.notify.telegraph import get_page
from scripts.prepare_article_repairs import DEBRIS, semantic_tree, text
from scripts.audit_channel_history import nodes


def links(content):
    return [(key, node["attrs"][key]) for node in nodes({"children": content})
            for key in ("href", "src") if key in node.get("attrs", {})]


def codes(content):
    return [(node["tag"], text(node)) for node in nodes({"children": content})
            if node.get("tag") in {"code", "pre"}]


def compare(page, plan):
    actual = page.get("content", [])
    expected = plan["content"]
    return {
        "title_matches": page.get("title") == plan["title"],
        "text_matches": text(actual) == text(expected),
        "links_match": links(actual) == links(expected),
        "code_matches": codes(actual) == codes(expected),
        "structure_matches": semantic_tree(actual) == semantic_tree(expected),
        "no_html_debris": not bool(DEBRIS.search(text(actual))),
    }


def main():
    directory = ROOT / "output/channel-review"
    plans = json.loads((directory / "article-repairs.json").read_text())["plans"]
    verified = []
    skipped = []
    for plan in plans:
        record = json.loads((directory / "article-results" / (plan["path"] + ".json")).read_text())
        if not record.get("ok"):
            skipped.append({"url": plan["url"], "path": plan["path"], "reason": record.get("error")})
            continue
        checks = compare(record["after"], plan)
        verified.append({
            "url": plan["url"], "checks": checks,
            "code_repairs": len(plan["checks"]["code_changes"]),
            "space_repairs": len(plan["checks"]["space_changes"]),
            "all_code_repairs_source_verified": all(c["verified_in_source"] for c in plan["checks"]["code_changes"]),
        })
    targets = [p for p in plans if any(marker in p["path"] for marker in (
        "Hermes-Agent-v0212-", "Hermes-Agent-v0213-", "Claude-Code-21273-", "OpenClaw-202683-",
    ))]
    public = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for plan, response in zip(targets, pool.map(lambda p: get_page(p["path"]), targets)):
            if not response.get("success"):
                public.append({"url": plan["url"], "error": response.get("error")})
                continue
            page = response["page"]
            checks = compare(page, plan)
            visible = text(page["content"])
            if "Hermes-Agent-v0212-" in plan["path"]:
                checks["doctor_recovery_present"] = "hermes doctor" in visible and "hermes sessions recover --inspect-only" in visible
                checks["media_profile_exfiltration_meaning_retained"] = all(s in visible for s in ("MEDIA:", ".env", "auth.json", "其他 profile"))
            elif "Hermes-Agent-v0213-" in plan["path"]:
                checks["english_and_chinese_present"] = "English" in visible and "中文" in visible
                checks["blockquote_preserved"] = any(n.get("tag") == "blockquote" for n in nodes({"children": page["content"]}))
            elif "Claude-Code-21273-" in plan["path"]:
                checks["permission_meaning_corrected"] = "time -p make build 这样的命令现在会再次请求授权，而不再直接被拒绝" in visible
                checks["stray_prompt_removed"] = "prompt 这样的命令" not in visible
            elif "OpenClaw-202683-" in plan["path"]:
                checks["historical_unreleased_correction_present"] = "Development Notes" in page["title"] and "Unreleased" in visible and "历史更正" in visible
                checks["official_release_index_linked"] = ("href", "https://github.com/openclaw/openclaw/releases") in links(page["content"])
            public.append({"url": plan["url"], "title": page["title"], "checks": checks})
    for item in skipped:
        response = get_page(item["path"])
        plan = next(p for p in plans if p["path"] == item["path"])
        item["public_read_succeeded"] = response.get("success", False)
        item["original_content_unchanged"] = bool(response.get("success") and response["page"]["content"] == plan["before_content"])
        item["original_title_unchanged"] = bool(response.get("success") and response["page"]["title"] == plan["before_title"])
    summary = {
        "planned_articles": len(plans), "applied_articles": len(verified), "skipped_articles": len(skipped),
        "actual_code_repairs": sum(v["code_repairs"] for v in verified),
        "actual_space_repairs": sum(v["space_repairs"] for v in verified),
        "all_stored_readbacks_match_latest_plan": all(all(v["checks"].values()) for v in verified),
        "all_code_repairs_source_verified": all(v["all_code_repairs_source_verified"] for v in verified),
        "all_priority_public_reads_pass": len(public) == 4 and all(p.get("checks") and all(p["checks"].values()) for p in public),
        "all_skipped_articles_unchanged": all(s["original_content_unchanged"] and s["original_title_unchanged"] for s in skipped),
    }
    report = {"summary": summary, "verified_articles": verified, "priority_public_reads": public, "skipped_articles": skipped}
    (directory / "article-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
