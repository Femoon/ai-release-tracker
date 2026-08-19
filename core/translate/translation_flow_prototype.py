#!/usr/bin/env python3
"""PROTOTYPE: compare the current translation flow with guarded translation.

This script is intentionally not imported by production code. It performs live
LLM calls without using the translation cache or sending notifications.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from litellm import completion


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

CHANGELOG_URL = (
    "https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md"
)
VERSIONS = ("2.1.232", "2.1.233", "2.1.234")
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
PROVIDER = "StreamLake"
MAX_TOKENS = 16384

KEEP_TERMS = (
    "Model Context Protocol",
    "full-strength redaction",
    "Background Task",
    "Thinking Block",
    "Transcript Mode",
    "reasoning effort",
    "Remote Control",
    "Plugin marketplace",
    "context window",
    "prompt cache",
    "Permission",
    "Frontmatter",
    "Sub-agent",
    "multi-agent",
    "Subagent",
    "WebSocket",
    "Streaming",
    "Sandbox",
    "Tool Use",
    "Tool Call",
    "Bash Tool",
    "Memory",
    "Prompt",
    "Plugin",
    "Skill",
    "Agent",
    "Hook",
    "OAuth",
    "Token",
    "worktree",
    "auto mode",
    "Focus view",
    "Compact Mode",
    "Plan Mode",
    "Code Mode",
    "exec_command",
    "apply_patch",
    "MCP",
    "TUI",
    "LLM",
    "CLI",
    "SDK",
    "API",
)

FIXED_TRANSLATIONS = {
    "context cost": "上下文开销",
    "newer models": "更新的模型",
    "full-strength redaction": "完整强度脱敏",
}

TERMINOLOGY_INSTRUCTION = (
    "专业术语规则（必须遵守）：以下 CLI 术语及其大小写、单复数、连字符变体必须原样保留："
    "API, SDK, CLI, Token, OAuth, WebSocket, Streaming, LLM, Prompt, Agent, Subagent, "
    "Sub-agent, multi-agent, Skill, Hook, Plugin, MCP, Model Context Protocol, TUI, Sandbox, "
    "worktree, prompt cache, context window, reasoning effort, Tool Use, Tool Call, Bash Tool, "
    "Permission, Thinking Block, Frontmatter, Background Task, Memory, Transcript Mode, "
    "exec_command, apply_patch, Remote Control, Code Mode, Plan Mode, Compact Mode, Focus view, "
    "auto mode。Agent 仅在表示 CLI 协作执行单元时保留英文；proxy、user agent 等其他含义"
    "按语境翻译。不确定的产品功能名保留英文。"
)

SYSTEM_PROMPT = f"""你是技术软件更新日志翻译器。只输出中文译文，不输出解释。

要求：
- 逐行翻译，禁止总结、合并、删除或重新组织内容
- 保持标题、列表项数量、顺序、缩进和 Markdown 格式不变
- 每个形如 [[KEEP_0000_ABCD]] 的 placeholder 必须逐字复制一次，禁止改写、删除、重复或重排
- 不要添加原文没有的标题、前言、结尾或说明
- commit 前缀 fix/feat/chore 等保留英文
- 中文表达自然、准确，符合技术文档习惯
"""


@dataclass(frozen=True)
class Placeholder:
    token: str
    source: str
    replacement: str
    line_index: int


@dataclass
class CallResult:
    content: str
    finish_reason: str
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float | None
    response_model: str
    error: str = ""


@dataclass
class Metrics:
    response_violations: int
    preserved_term_violations: int
    fixed_translation_violations: int
    line_count_difference: int
    bullet_structure_violations: int
    heading_structure_violations: int
    inline_code_violations: int
    url_violations: int
    placeholder_violations: int
    chinese_ratio: float

    @property
    def hard_violations(self) -> int:
        return (
            self.response_violations
            + self.preserved_term_violations
            + self.fixed_translation_violations
            + self.line_count_difference
            + self.bullet_structure_violations
            + self.heading_structure_violations
            + self.inline_code_violations
            + self.url_violations
            + self.placeholder_violations
        )


def _baseline_prompt(content: str) -> str:
    return f"""请将以下软件更新日志逐条翻译成中文，直接输出翻译结果。

关键要求（必须严格遵守）：
- 逐行翻译，禁止总结、合并或重新组织内容
- 每个列表项（以 - 或 • 开头的行）必须单独翻译，不能合并成段落
- 保持原文的结构和格式不变，翻译后的行数应与原文基本一致
- 不要添加标题、摘要或任何原文没有的内容

翻译示例（必须遵守）：
- "• Added new feature" → "• 新增功能"
- "• Fixed bug in API" → "• 修复 API 中的错误"
- "• Changed default behavior" → "• 变更默认行为"
- "• Removed deprecated option" → "• 移除已弃用的选项"
- "- fix: resolve issue" → "- fix: 解决问题"（commit 前缀 fix/feat/chore 等保留英文）

格式要求：
1. 保持 Markdown 格式不变（标题、列表、代码块等）
2. 版本号、行内代码保持原样
3. GitHub 用户名、斜杠命令、配置文件名保持原样
4. 语言流畅自然，符合中文技术文档习惯

{TERMINOLOGY_INSTRUCTION}

待翻译内容：
{content}"""


def _parse_versions(changelog: str) -> dict[str, str]:
    wanted = set(VERSIONS)
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in changelog.splitlines():
        match = re.match(r"^## (\d+\.\d+\.\d+)", line)
        if match:
            version = match.group(1)
            current = version if version in wanted else None
            if current:
                found[current] = [line]
            continue
        if current:
            found[current].append(line)
    return {version: "\n".join(found[version]).strip() for version in VERSIONS if version in found}


def _keep_phrase_pattern() -> str:
    keep_phrases = sorted(set(KEEP_TERMS) - set(FIXED_TRANSLATIONS), key=len, reverse=True)
    keep_patterns = []
    for phrase in keep_phrases:
        escaped = re.escape(phrase)
        if phrase == "Memory":
            escaped = r"Memor(?:y|ies)"
        elif phrase == "Sandbox":
            escaped = r"Sandbox(?:es)?"
        elif phrase[-1].isalpha() and not phrase.endswith("s"):
            escaped = rf"{escaped}s?"
        keep_patterns.append(escaped)
    return "|".join(keep_patterns)


KEEP_PATTERN_TEXT = _keep_phrase_pattern()
KEEP_MATCH_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_])(?i:{KEEP_PATTERN_TEXT})(?![A-Za-z0-9_])"
)


def _protection_pattern() -> re.Pattern[str]:
    fixed_pattern = "|".join(
        re.escape(phrase) for phrase in sorted(FIXED_TRANSLATIONS, key=len, reverse=True)
    )
    return re.compile(
        rf"```[\s\S]*?```|`[^`\n]+`|https?://[^\s)>]+|"
        rf"(?<![\w@])@[A-Za-z0-9][A-Za-z0-9_-]*|"
        rf"(?<![A-Za-z0-9_])(?:{fixed_pattern})(?![A-Za-z0-9_])|"
        rf"(?<![A-Za-z0-9_])(?i:{KEEP_PATTERN_TEXT})(?![A-Za-z0-9_])|"
        rf"(?<![A-Za-z0-9_])v?\d+(?:\.\d+){{1,3}}(?:[-+][A-Za-z0-9_.-]+)?(?![A-Za-z0-9_])"
    )


PROTECTION_PATTERN = _protection_pattern()


def protect(content: str) -> tuple[str, list[Placeholder]]:
    placeholders: list[Placeholder] = []
    cursor = 0
    parts: list[str] = []
    line_index = 0
    for match in PROTECTION_PATTERN.finditer(content):
        before = content[cursor : match.start()]
        parts.append(before)
        line_index += before.count("\n")
        source = match.group(0)
        suffix = f"{sum(source.encode('utf-8')) & 0xFFFF:04X}"
        token = f"[[KEEP_{len(placeholders):04d}_{suffix}]]"
        if token in content:
            raise ValueError(f"placeholder collision: {token}")
        replacement = FIXED_TRANSLATIONS.get(source, source)
        placeholders.append(Placeholder(token, source, replacement, line_index))
        parts.append(token)
        cursor = match.end()
    parts.append(content[cursor:])
    return "".join(parts), placeholders


def restore(content: str, placeholders: list[Placeholder]) -> str:
    restored = content
    for placeholder in placeholders:
        restored = restored.replace(placeholder.token, placeholder.replacement)
    restored = re.sub(r"(?<=[\u4e00-\u9fff]) +(?=[\u4e00-\u9fff])", "", restored)
    return restored


def _bullet_signature(text: str) -> list[tuple[int, str, int]]:
    signature = []
    for index, line in enumerate(text.splitlines()):
        match = re.match(r"^(\s*)([-*+•]|\d+[.)])\s+", line)
        if match:
            signature.append((index, match.group(2), len(match.group(1))))
    return signature


def _heading_signature(text: str) -> list[tuple[int, int]]:
    signature = []
    for index, line in enumerate(text.splitlines()):
        match = re.match(r"^(#{1,6})\s+", line)
        if match:
            signature.append((index, len(match.group(1))))
    return signature


def _count_differences(left: list[Any], right: list[Any]) -> int:
    shared = min(len(left), len(right))
    return sum(left[index] != right[index] for index in range(shared)) + abs(
        len(left) - len(right)
    )


def _term_violations(source: str, translated: str) -> int:
    expected = Counter(match.group(0) for match in KEEP_MATCH_PATTERN.finditer(source))
    return sum(max(0, count - translated.count(term)) for term, count in expected.items())


def _fixed_translation_violations(source: str, translated: str) -> int:
    return sum(
        max(0, source.count(term) - translated.count(target))
        for term, target in FIXED_TRANSLATIONS.items()
    )


def _placeholder_issues(
    protected_source: str,
    candidate: str,
    placeholders: list[Placeholder],
) -> tuple[int, set[int], bool]:
    expected = [placeholder.token for placeholder in placeholders]
    actual = re.findall(r"\[\[KEEP_\d{4}_[0-9A-F]{4}\]\]", candidate)
    violation_count = _count_differences(expected, actual)
    affected_lines: set[int] = set()
    expected_counter = Counter(expected)
    actual_counter = Counter(actual)
    for placeholder in placeholders:
        if actual_counter[placeholder.token] != expected_counter[placeholder.token]:
            affected_lines.add(placeholder.line_index)
    if expected != actual:
        for index, token in enumerate(expected):
            if index >= len(actual) or token != actual[index]:
                affected_lines.add(placeholders[index].line_index)

    source_lines = protected_source.splitlines()
    candidate_lines = candidate.splitlines()
    repairable = len(source_lines) == len(candidate_lines)
    if repairable:
        source_bullets = _bullet_signature(protected_source)
        candidate_bullets = _bullet_signature(candidate)
        if len(source_bullets) != len(candidate_bullets):
            repairable = False
        else:
            for source_item, candidate_item in zip(source_bullets, candidate_bullets):
                if source_item != candidate_item:
                    affected_lines.add(source_item[0])
    return violation_count, affected_lines, repairable


def measure(
    source: str,
    translated: str,
    *,
    protected_source: str = "",
    protected_candidate: str = "",
    placeholders: list[Placeholder] | None = None,
) -> Metrics:
    placeholders = placeholders or []
    if not translated:
        return Metrics(
            response_violations=1,
            preserved_term_violations=0,
            fixed_translation_violations=0,
            line_count_difference=0,
            bullet_structure_violations=0,
            heading_structure_violations=0,
            inline_code_violations=0,
            url_violations=0,
            placeholder_violations=0,
            chinese_ratio=0.0,
        )
    placeholder_violations = 0
    if placeholders:
        placeholder_violations, _, _ = _placeholder_issues(
            protected_source, protected_candidate, placeholders
        )
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", translated))
    return Metrics(
        response_violations=0,
        preserved_term_violations=_term_violations(source, translated),
        fixed_translation_violations=_fixed_translation_violations(source, translated),
        line_count_difference=abs(len(source.splitlines()) - len(translated.splitlines())),
        bullet_structure_violations=_count_differences(
            _bullet_signature(source), _bullet_signature(translated)
        ),
        heading_structure_violations=_count_differences(
            _heading_signature(source), _heading_signature(translated)
        ),
        inline_code_violations=_count_differences(
            re.findall(r"`[^`\n]+`", source), re.findall(r"`[^`\n]+`", translated)
        ),
        url_violations=_count_differences(
            re.findall(r"https?://[^\s)>]+", source),
            re.findall(r"https?://[^\s)>]+", translated),
        ),
        placeholder_violations=placeholder_violations,
        chinese_ratio=(chinese_count / len(translated)) if translated else 0.0,
    )


def call_llm(messages: list[dict[str, str]], api_key: str) -> CallResult:
    started = time.perf_counter()
    try:
        response = completion(
            model=MODEL,
            api_key=api_key,
            messages=messages,
            temperature=0.3,
            max_tokens=MAX_TOKENS,
            extra_body={
                "provider": {
                    "only": [PROVIDER],
                    "allow_fallbacks": False,
                }
            },
        )
        latency = time.perf_counter() - started
        if not response.choices:
            return CallResult("", "", latency, 0, 0, 0, None, "", "empty choices")
        choice = response.choices[0]
        content = choice.message.content or ""
        usage = response.usage
        hidden = getattr(response, "_hidden_params", {}) or {}
        headers = hidden.get("additional_headers", {}) or {}
        cost = headers.get("llm_provider-x-litellm-response-cost")
        return CallResult(
            content=content.strip(),
            finish_reason=str(choice.finish_reason or ""),
            latency_seconds=round(latency, 3),
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            cost=float(cost) if cost is not None else None,
            response_model=str(getattr(response, "model", "") or ""),
        )
    except Exception as exc:
        return CallResult(
            "", "", round(time.perf_counter() - started, 3), 0, 0, 0, None, "", str(exc)
        )


def run_baseline(source: str, api_key: str) -> dict[str, Any]:
    call = call_llm([{"role": "user", "content": _baseline_prompt(source)}], api_key)
    metrics = measure(source, call.content)
    return {
        "translation": call.content,
        "calls": [asdict(call)],
        "metrics": {**asdict(metrics), "hard_violations": metrics.hard_violations},
    }


def _parse_repair_response(raw: str) -> dict[str, str]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("repair response must be a JSON object")
    if isinstance(parsed.get("line"), int) and isinstance(parsed.get("repaired"), str):
        return {str(parsed["line"]): parsed["repaired"]}
    return {str(key): value for key, value in parsed.items() if isinstance(value, str)}


def _apply_repair_response(
    candidate: str,
    affected_lines: set[int],
    raw_response: str,
) -> str:
    candidate_lines = candidate.splitlines()
    replacements = _parse_repair_response(raw_response)
    for line_index in sorted(affected_lines):
        value = replacements.get(str(line_index))
        if isinstance(value, str) and line_index < len(candidate_lines):
            candidate_lines[line_index] = value
    return "\n".join(candidate_lines)


def _repair_lines(
    protected_source: str,
    candidate: str,
    affected_lines: set[int],
    api_key: str,
) -> tuple[str, CallResult]:
    source_lines = protected_source.splitlines()
    candidate_lines = candidate.splitlines()
    items = []
    for line_index in sorted(affected_lines):
        if line_index >= len(source_lines) or line_index >= len(candidate_lines):
            continue
        items.append(
            {
                "line": line_index,
                "source": source_lines[line_index],
                "current_translation": candidate_lines[line_index],
                "error": "Restore every placeholder exactly once and preserve the list marker.",
            }
        )
    repair_prompt = (
        "Repair only the listed translated lines. Return one JSON object mapping each numeric "
        "line value to its repaired string. Do not use Markdown fences. Preserve every "
        "[[KEEP_...]] placeholder exactly.\n\n"
        + json.dumps(items, ensure_ascii=False)
    )
    call = call_llm(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": repair_prompt},
        ],
        api_key,
    )
    repaired = candidate
    if not call.content:
        return repaired, call
    try:
        repaired = _apply_repair_response(candidate, affected_lines, call.content)
    except (json.JSONDecodeError, ValueError):
        call.error = "repair response was not valid JSON"
        return repaired, call
    return repaired, call


def run_guarded(source: str, api_key: str) -> dict[str, Any]:
    protected_source, placeholders = protect(source)
    first = call_llm(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"<SOURCE>\n{protected_source}\n</SOURCE>"},
        ],
        api_key,
    )
    calls = [first]
    protected_candidate = first.content
    placeholder_count, affected_lines, repairable = _placeholder_issues(
        protected_source, protected_candidate, placeholders
    )
    structure_metrics = measure(
        source,
        restore(protected_candidate, placeholders),
        protected_source=protected_source,
        protected_candidate=protected_candidate,
        placeholders=placeholders,
    )
    needs_repair = bool(
        protected_candidate
        and first.finish_reason != "length"
        and (
            placeholder_count
            or structure_metrics.line_count_difference
            or structure_metrics.bullet_structure_violations
            or structure_metrics.heading_structure_violations
        )
    )
    if needs_repair and repairable and affected_lines:
        protected_candidate, repair_call = _repair_lines(
            protected_source, protected_candidate, affected_lines, api_key
        )
        calls.append(repair_call)

    translated = restore(protected_candidate, placeholders)
    metrics = measure(
        source,
        translated,
        protected_source=protected_source,
        protected_candidate=protected_candidate,
        placeholders=placeholders,
    )
    return {
        "translation": translated,
        "calls": [asdict(call) for call in calls],
        "repair_attempted": len(calls) == 2,
        "repairable": repairable,
        "affected_lines": sorted(affected_lines),
        "metrics": {**asdict(metrics), "hard_violations": metrics.hard_violations},
    }


def _report(results: dict[str, Any]) -> str:
    lines = [
        "# Translation Flow Prototype Benchmark",
        "",
        f"- Model: `{MODEL}`",
        f"- Provider: `{PROVIDER}` (fallback disabled)",
        "- Temperature: `0.3`",
        "",
        "| Version | Flow | Calls | Response | Hard violations | Terms | Fixed translations | Bullets | Inline code | Latency |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for version in VERSIONS:
        for flow in ("baseline", "guarded"):
            result = results["versions"][version][flow]
            metrics = result["metrics"]
            latency = sum(call["latency_seconds"] for call in result["calls"])
            lines.append(
                f"| {version} | {flow} | {len(result['calls'])} | "
                f"{metrics['response_violations']} | {metrics['hard_violations']} | "
                f"{metrics['preserved_term_violations']} | "
                f"{metrics['fixed_translation_violations']} | "
                f"{metrics['bullet_structure_violations']} | "
                f"{metrics['inline_code_violations']} | {latency:.1f}s |"
            )
    lines.extend(["", "## Decision", "", results["decision"], ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--versions",
        nargs="*",
        default=list(VERSIONS),
        choices=VERSIONS,
        help="Claude Code versions to benchmark",
    )
    args = parser.parse_args()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    configured_model = os.getenv("LLM_MODEL", "").strip()
    if not api_key:
        print("LLM_API_KEY is not configured", file=sys.stderr)
        return 2
    if configured_model != MODEL:
        print(f"LLM_MODEL must be exactly {MODEL}; got {configured_model!r}", file=sys.stderr)
        return 2

    response = requests.get(CHANGELOG_URL, timeout=30)
    response.raise_for_status()
    versions = _parse_versions(response.text)
    missing = set(args.versions) - set(versions)
    if missing:
        print(f"Versions not found: {sorted(missing)}", file=sys.stderr)
        return 2

    results: dict[str, Any] = {
        "created_at": datetime.now().astimezone().isoformat(),
        "model": MODEL,
        "provider": PROVIDER,
        "versions": {},
    }
    for version in args.versions:
        source = versions[version]
        print(f"[{version}] baseline", flush=True)
        baseline = run_baseline(source, api_key)
        print(
            f"[{version}] baseline hard violations: {baseline['metrics']['hard_violations']}",
            flush=True,
        )
        print(f"[{version}] guarded", flush=True)
        guarded = run_guarded(source, api_key)
        print(
            f"[{version}] guarded hard violations: {guarded['metrics']['hard_violations']} "
            f"({len(guarded['calls'])} calls)",
            flush=True,
        )
        results["versions"][version] = {
            "source": source,
            "baseline": baseline,
            "guarded": guarded,
        }

    baseline_total = sum(
        data["baseline"]["metrics"]["hard_violations"]
        for data in results["versions"].values()
    )
    guarded_total = sum(
        data["guarded"]["metrics"]["hard_violations"]
        for data in results["versions"].values()
    )
    structural_regressions = sum(
        data["guarded"]["metrics"][field]
        for data in results["versions"].values()
        for field in (
            "line_count_difference",
            "bullet_structure_violations",
            "heading_structure_violations",
            "inline_code_violations",
            "url_violations",
        )
    )
    improvement = ((baseline_total - guarded_total) / baseline_total) if baseline_total else 0
    passed = (
        baseline_total > 0
        and guarded_total == 0
        and structural_regressions == 0
        and improvement >= 0.8
    )
    results["summary"] = {
        "baseline_hard_violations": baseline_total,
        "guarded_hard_violations": guarded_total,
        "improvement_ratio": improvement,
        "structural_regressions": structural_regressions,
        "passed": passed,
    }
    if passed:
        results["decision"] = (
            "PASS: guarded translation removed all measured hard violations without structural regression."
        )
    elif baseline_total == 0:
        results["decision"] = (
            "INCONCLUSIVE: the baseline had no measured hard violations in this run."
        )
    else:
        results["decision"] = (
            "FAIL: guarded translation did not satisfy the predefined production gate."
        )

    output_dir = PROJECT_ROOT / "output" / "translation_benchmark"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"benchmark_{timestamp}.json"
    report_path = output_dir / f"benchmark_{timestamp}.md"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_report(results), encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Report: {report_path}")
    print(results["decision"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
