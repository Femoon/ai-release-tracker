"""Deterministic protection and validation for changelog translations."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass


KEEP_TERMS = (
    "Model Context Protocol",
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
    "专业术语规则：CLI 专业术语（包括大小写和复数变体）必须保留英文；"
    "不确定的产品功能名保留英文。"
)


@dataclass(frozen=True)
class Placeholder:
    token: str
    source: str
    replacement: str
    line_index: int


@dataclass(frozen=True)
class ProtectedDocument:
    source: str
    protected: str
    placeholders: tuple[Placeholder, ...]


@dataclass(frozen=True)
class TokenDiff:
    """单个逻辑行上的 placeholder 差异，用于给模型精确的修复指令。"""

    line_index: int
    missing: tuple[str, ...]
    extra: tuple[str, ...]


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issue_count: int
    affected_lines: frozenset[int]
    repairable: bool
    reasons: tuple[str, ...]
    token_issue_count: int = 0
    structure_issue_count: int = 0
    token_diffs: tuple[TokenDiff, ...] = ()


# 降级放行阈值：结构完好、只剩少量 placeholder 偏差时，宁可接受略有瑕疵的
# 中文译文，也不要整段丢弃只发英文。
# 短文本（placeholder 少于 DEGRADED_MIN_PLACEHOLDERS）不降级：那里一处偏差
# 占比很高，且重试/修复成本低，继续 fail closed。
DEGRADED_MIN_PLACEHOLDERS = 20
DEGRADED_TOKEN_TOLERANCE_RATIO = 0.05
DEGRADED_TOKEN_TOLERANCE_MAX = 10


def _keep_phrase_pattern() -> str:
    patterns = []
    for phrase in sorted(KEEP_TERMS, key=len, reverse=True):
        escaped = re.escape(phrase)
        if phrase == "Memory":
            escaped = r"Memor(?:y|ies)"
        elif phrase == "Sandbox":
            escaped = r"Sandbox(?:es)?"
        elif phrase[-1].isalpha() and not phrase.endswith("s"):
            escaped = rf"{escaped}s?"
        patterns.append(escaped)
    return "|".join(patterns)


_KEEP_PATTERN_TEXT = _keep_phrase_pattern()
_FIXED_PATTERN_TEXT = "|".join(
    re.escape(phrase) for phrase in sorted(FIXED_TRANSLATIONS, key=len, reverse=True)
)
_PROTECTION_PATTERN = re.compile(
    rf"```[\s\S]*?```|`[^`\n]+`|https?://[^\s)>]+|"
    rf"(?<![\w@])@[A-Za-z0-9][A-Za-z0-9_-]*|"
    rf"(?<![A-Za-z0-9_])(?:{_FIXED_PATTERN_TEXT})(?![A-Za-z0-9_])|"
    rf"(?<![A-Za-z0-9_])(?i:{_KEEP_PATTERN_TEXT})(?![A-Za-z0-9_])|"
    rf"(?<![A-Za-z0-9_])v?\d+(?:\.\d+){{1,3}}(?:[-+][A-Za-z0-9_.-]+)?(?![A-Za-z0-9_])"
)
_TOKEN_PATTERN = re.compile(r"\[\[KEEP_\d{4}_[0-9A-F]{4}\]\]")


def protect(content: str) -> ProtectedDocument:
    placeholders: list[Placeholder] = []
    parts: list[str] = []
    cursor = 0
    line_index = 0
    for match in _PROTECTION_PATTERN.finditer(content):
        before = content[cursor : match.start()]
        parts.append(before)
        line_index += before.count("\n")
        source = match.group(0)
        if source.lower() in {"agent", "agents"} and re.search(
            r"\b(?:proxy|user)\s+$", content[max(0, match.start() - 12) : match.start()], re.I
        ):
            parts.append(source)
            cursor = match.end()
            continue
        suffix = f"{sum(source.encode('utf-8')) & 0xFFFF:04X}"
        token = f"[[KEEP_{len(placeholders):04d}_{suffix}]]"
        if token in content:
            raise ValueError(f"placeholder collision: {token}")
        placeholders.append(
            Placeholder(
                token=token,
                source=source,
                replacement=FIXED_TRANSLATIONS.get(source, source),
                line_index=line_index,
            )
        )
        parts.append(token)
        cursor = match.end()
    parts.append(content[cursor:])
    return ProtectedDocument(content, "".join(parts), tuple(placeholders))


def restore(document: ProtectedDocument, candidate: str) -> str:
    restored = candidate
    for placeholder in document.placeholders:
        restored = restored.replace(placeholder.token, placeholder.replacement)
    return re.sub(r"(?<=[\u4e00-\u9fff]) +(?=[\u4e00-\u9fff])", "", restored)


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


def validate(document: ProtectedDocument, candidate: str) -> ValidationResult:
    reasons: list[str] = []
    affected_lines: set[int] = set()
    source_physical_lines = document.protected.splitlines()
    candidate_physical_lines = candidate.splitlines()
    source_lines = [
        (index, line)
        for index, line in enumerate(source_physical_lines)
        if line.strip()
    ]
    candidate_lines = [
        (index, line)
        for index, line in enumerate(candidate_physical_lines)
        if line.strip()
    ]

    # Placeholder order may change inside a sentence during translation, but a
    # protected token must remain in its original source line. This catches
    # cross-item moves without rejecting natural Chinese word order. Blank
    # lines are formatting only and do not change logical line ownership.
    token_issue_count = 0
    token_diffs: list[TokenDiff] = []
    for line_index in range(min(len(source_lines), len(candidate_lines))):
        source_physical_index, source_line = source_lines[line_index]
        _, candidate_line = candidate_lines[line_index]
        expected_line = Counter(_TOKEN_PATTERN.findall(source_line))
        actual_line = Counter(_TOKEN_PATTERN.findall(candidate_line))
        missing = expected_line - actual_line
        extra = actual_line - expected_line
        difference = sum(missing.values()) + sum(extra.values())
        if difference:
            token_issue_count += difference
            affected_lines.add(source_physical_index)
            token_diffs.append(
                TokenDiff(
                    line_index=source_physical_index,
                    missing=tuple(sorted(missing.elements())),
                    extra=tuple(sorted(extra.elements())),
                )
            )
    if len(source_lines) != len(candidate_lines):
        shared_count = min(len(source_lines), len(candidate_lines))
        for source_physical_index, line in source_lines[shared_count:]:
            token_issue_count += len(_TOKEN_PATTERN.findall(line))
            affected_lines.add(source_physical_index)
        for _, line in candidate_lines[shared_count:]:
            token_issue_count += len(_TOKEN_PATTERN.findall(line))
    if token_issue_count:
        reasons.append(f"placeholder violations: {token_issue_count}")

    line_difference = abs(len(source_lines) - len(candidate_lines))
    if line_difference:
        reasons.append(f"line count difference: {line_difference}")

    source_logical_text = "\n".join(line for _, line in source_lines)
    candidate_logical_text = "\n".join(line for _, line in candidate_lines)
    source_bullets = _bullet_signature(source_logical_text)
    candidate_bullets = _bullet_signature(candidate_logical_text)
    bullet_difference = 0
    for index in range(min(len(source_bullets), len(candidate_bullets))):
        if source_bullets[index] != candidate_bullets[index]:
            bullet_difference += 1
            affected_lines.add(source_lines[source_bullets[index][0]][0])
    bullet_difference += abs(len(source_bullets) - len(candidate_bullets))
    if bullet_difference:
        reasons.append(f"bullet structure violations: {bullet_difference}")

    source_headings = _heading_signature(source_logical_text)
    candidate_headings = _heading_signature(candidate_logical_text)
    heading_difference = 0
    for index in range(min(len(source_headings), len(candidate_headings))):
        if source_headings[index] != candidate_headings[index]:
            heading_difference += 1
            affected_lines.add(source_lines[source_headings[index][0]][0])
    heading_difference += abs(len(source_headings) - len(candidate_headings))
    if heading_difference:
        reasons.append(f"heading structure violations: {heading_difference}")

    structure_issue_count = line_difference + bullet_difference + heading_difference
    issue_count = token_issue_count + structure_issue_count
    blank_layout_same = [not line.strip() for line in source_physical_lines] == [
        not line.strip() for line in candidate_physical_lines
    ]
    repairable = (
        blank_layout_same
        and len(source_lines) == len(candidate_lines)
        and len(source_bullets) == len(candidate_bullets)
        and len(source_headings) == len(candidate_headings)
        and bool(affected_lines)
    )
    return ValidationResult(
        valid=issue_count == 0,
        issue_count=issue_count,
        affected_lines=frozenset(affected_lines),
        repairable=repairable,
        reasons=tuple(reasons),
        token_issue_count=token_issue_count,
        structure_issue_count=structure_issue_count,
        token_diffs=tuple(token_diffs),
    )


def _drop_token_occurrences(line: str, token: str, count: int) -> str:
    """从行尾开始删除 count 个 token，保留最前面的合法出现。"""
    for _ in range(count):
        index = line.rfind(token)
        if index < 0:
            break
        end = index + len(token)
        if line[end : end + 1] == " ":
            end += 1
        elif index > 0 and line[index - 1] == " ":
            index -= 1
        line = line[:index] + line[end:]
    return line


def repair_placeholders(document: ProtectedDocument, candidate: str) -> tuple[str, int]:
    """
    确定性修复：删除模型多复制出来的 placeholder。

    只删除在“所属逻辑行”和“全文”同时超量的 token，因此不会误删跨行搬移的
    token（那类问题仍交给模型定向修复）。中文自然语序常把同一个术语重复一次
    （例如 "禁用 X 时 X 报告失败"），这类偏差机械可修，不该整段丢弃译文。

    Returns:
        (修复后的候选译文, 删除的 placeholder 数量)
    """
    source_lines = [line for line in document.protected.splitlines() if line.strip()]
    candidate_physical = candidate.splitlines()
    candidate_indices = [
        index for index, line in enumerate(candidate_physical) if line.strip()
    ]
    if len(source_lines) != len(candidate_indices):
        return candidate, 0

    surplus = Counter(_TOKEN_PATTERN.findall(candidate)) - Counter(
        _TOKEN_PATTERN.findall(document.protected)
    )
    if not surplus:
        return candidate, 0

    removed = 0
    for logical_index, physical_index in enumerate(candidate_indices):
        expected = Counter(_TOKEN_PATTERN.findall(source_lines[logical_index]))
        line = candidate_physical[physical_index]
        actual = Counter(_TOKEN_PATTERN.findall(line))
        for token, count in (actual - expected).items():
            drop = min(count, surplus[token])
            if drop <= 0:
                continue
            line = _drop_token_occurrences(line, token, drop)
            surplus[token] -= drop
            removed += drop
        candidate_physical[physical_index] = line

    if not removed:
        return candidate, 0
    return "\n".join(candidate_physical), removed


def degraded_tolerance(placeholder_count: int) -> int:
    """允许降级放行的 placeholder 偏差上限；0 表示不允许降级。"""
    if placeholder_count < DEGRADED_MIN_PLACEHOLDERS:
        return 0
    scaled = math.ceil(placeholder_count * DEGRADED_TOKEN_TOLERANCE_RATIO)
    return min(DEGRADED_TOKEN_TOLERANCE_MAX, max(1, scaled))


def is_acceptable_degradation(
    document: ProtectedDocument,
    validation: ValidationResult,
) -> bool:
    """
    判断能否降级接受这份译文。

    结构（行数、列表项、标题）必须完好；只有少量 placeholder 偏差时，还原术语后
    最坏结果是个别术语缺失或重复，仍远好于只发英文原文。
    """
    if validation.valid:
        return True
    if validation.structure_issue_count:
        return False
    tolerance = degraded_tolerance(len(document.placeholders))
    if not tolerance:
        return False
    return 0 < validation.token_issue_count <= tolerance


def repair_items(
    document: ProtectedDocument,
    candidate: str,
    validation: ValidationResult,
) -> list[dict[str, object]]:
    source_lines = document.protected.splitlines()
    candidate_lines = candidate.splitlines()
    diffs = {diff.line_index: diff for diff in validation.token_diffs}
    items = []
    for line_index in sorted(validation.affected_lines):
        diff = diffs.get(line_index)
        items.append(
            {
                "line": line_index,
                "source": source_lines[line_index],
                "current_translation": candidate_lines[line_index],
                "missing_placeholders": list(diff.missing) if diff else [],
                "extra_placeholders": list(diff.extra) if diff else [],
                "errors": list(validation.reasons),
            }
        )
    return items


def apply_repair(
    candidate: str,
    affected_lines: frozenset[int],
    response_content: str,
) -> str:
    raw = response_content.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("repair response must be a JSON object")
    if isinstance(parsed.get("line"), int) and isinstance(parsed.get("repaired"), str):
        replacements = {str(parsed["line"]): parsed["repaired"]}
    else:
        replacements = {
            str(key): value for key, value in parsed.items() if isinstance(value, str)
        }

    candidate_lines = candidate.splitlines()
    for line_index in sorted(affected_lines):
        replacement = replacements.get(str(line_index))
        if replacement is not None:
            candidate_lines[line_index] = replacement
    return "\n".join(candidate_lines)
