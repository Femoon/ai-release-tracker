#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译模块 - 使用 LiteLLM 调用 LLM API 进行翻译
"""

import json
import os
import re
from litellm import completion

from core.translate import cache as translation_cache
from core.translate.policy import (
    TERMINOLOGY_INSTRUCTION,
    apply_repair,
    degraded_tolerance,
    is_acceptable_degradation,
    protect,
    repair_items,
    repair_placeholders,
    restore,
    validate,
)


# 翻译质量检查：中文字符最低占比
MIN_CHINESE_RATIO = 0.05  # 5%
# 致命错误关键词：命中后立即终止重试，不再继续消耗 API 配额
# 包含两类：
# - 额度/配额类（重试也无济于事，且仍会扣费）：max_tokens / credits / 402 / quota / insufficient
# - 内容/权限类（同样的输入重试只会再次失败）：403 / prohibited / violation / content_policy / blocked
_FATAL_ERROR_KEYWORDS = (
    "max_tokens",
    "credits",
    "insufficient",
    "402",
    "403",
    "quota",
    "rate_limit_exceeded",
    "prohibited",
    "violation",
    "content_policy",
    "blocked",
)

# 显式给 LiteLLM completion 设置输出上限，避免 OpenRouter 默认 65536 触发
# "requires more credits / fewer max_tokens" 402 错误
_TRANSLATE_MIN_TOKENS = 8192
_TRANSLATE_MAX_TOKENS = 32768
_SUMMARIZE_MAX_TOKENS = 4096
_TRANSLATION_CACHE_KIND = "translate_guarded_v1"
# 定向修复最多处理的失败行数：超过说明整份译文的 placeholder 大面积错乱，
# 重新翻译比逐行修复更划算也更可靠
_REPAIR_MAX_LINES = 12
# summarize 的输入截断阈值：prompt 要求输出 < 2000 字符摘要，输入超过此阈值
# 时只保留前面部分（通常包含 Highlights / Breaking / New Features 等高价值段落），
# 避免把 70k+ 字符的 changelog 整个塞给 LLM 浪费输入 token
_SUMMARIZE_INPUT_TRUNCATE_CHARS = 24000

_TRANSLATION_SYSTEM_PROMPT = """你是技术软件更新日志翻译器。只输出中文译文，不输出解释。

要求：
- 逐行翻译，禁止总结、合并、删除或重新组织内容
- 保持标题、列表项数量、顺序、缩进和 Markdown 格式不变
- 每个形如 [[KEEP_0000_ABCD]] 的 placeholder 必须逐字复制一次，禁止改写、删除、重复或重排
- 不要添加原文没有的标题、前言、结尾或说明
- commit 前缀 fix/feat/chore 等保留英文
- 中文表达自然、准确，符合技术文档习惯
"""

_DEFAULT_REASONING_EFFORT = "none"


def _reasoning_effort() -> str:
    """
    reasoning effort，通过 LLM_REASONING_EFFORT 配置，默认 none（关闭思考）。

    部分模型（如 GLM 5.3 Flash）强制开启思考，effort=none 会被所有 provider
    以 400 拒绝，这类模型需要配置 minimal/low。思考 token 计入 max_tokens
    输出预算，effort 越高翻译越容易被截断。
    """
    return os.getenv("LLM_REASONING_EFFORT", "").strip() or _DEFAULT_REASONING_EFFORT


def _build_extra_body() -> dict:
    """
    构造 OpenRouter extra_body：设置 reasoning effort，并可选固定 provider。

    OpenRouter 会把同一个模型 slug 路由到不同 provider（量化/质量不同），
    翻译质量方差很大。设置 LLM_PROVIDER_ONLY（逗号分隔）可以把请求固定到
    指定 provider 白名单，例如 LLM_PROVIDER_ONLY=fireworks,deepinfra,together。
    未设置时不限制路由。注意 provider 需要和账号的数据策略兼容，否则会 404。
    """
    extra_body = {"reasoning": {"effort": _reasoning_effort()}}
    providers = [
        p.strip()
        for p in os.getenv("LLM_PROVIDER_ONLY", "").split(",")
        if p.strip()
    ]
    if providers:
        extra_body["provider"] = {"only": providers}
    return extra_body


def _is_fatal_error(err: Exception) -> bool:
    msg = str(err).lower()
    return any(kw in msg for kw in _FATAL_ERROR_KEYWORDS)


def _count_chinese_chars(text: str) -> int:
    """统计中文字符数量"""
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
    return len(chinese_pattern.findall(text))


def _check_translation_quality(translated: str) -> bool:
    """
    检查翻译质量

    Returns:
        bool: True 表示翻译有效，False 表示翻译失败（返回了英文原文）
    """
    if not translated:
        return False

    chinese_count = _count_chinese_chars(translated)
    total_length = len(translated)

    if total_length == 0:
        return False

    chinese_ratio = chinese_count / total_length

    return chinese_ratio >= MIN_CHINESE_RATIO


def _request_completion(
    *,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    response_format: dict | None = None,
) -> tuple[str, str]:
    kwargs = {
        "model": model,
        "api_key": api_key,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "extra_body": _build_extra_body(),
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    response = completion(**kwargs)
    if not response.choices:
        return "", "empty_choices"
    choice = response.choices[0]
    content = choice.message.content or ""
    return content.strip(), str(choice.finish_reason or "")


def _is_locally_repairable(validation) -> bool:
    """
    只有失败面足够小才值得定向修复。

    OpenRouter 会把同一个模型 slug 路由到不同 provider（量化不同），偶尔会返回
    placeholder 大面积错乱的译文。这种整份不可信的结果应该重新翻译，而不是花一次
    调用去修几十行。
    """
    return validation.repairable and len(validation.affected_lines) <= _REPAIR_MAX_LINES


def _validate_candidate(document, candidate: str):
    """先做确定性 placeholder 修复，再校验。返回 (候选译文, 校验结果)。"""
    validation = validate(document, candidate)
    if validation.valid:
        return candidate, validation

    repaired, removed = repair_placeholders(document, candidate)
    if not removed:
        return candidate, validation

    print(f"确定性修复: 移除 {removed} 个多余 placeholder")
    return repaired, validate(document, repaired)


def _accept_degraded(document, validation) -> bool:
    """结构完好且 placeholder 偏差极少时降级放行，避免整段译文被丢弃。"""
    if not is_acceptable_degradation(document, validation):
        return False
    print(
        f"翻译降级放行: placeholder 偏差 {validation.token_issue_count} 处"
        f"（阈值 {degraded_tolerance(len(document.placeholders))}，结构校验通过）"
    )
    return True


def _translation_max_tokens(content: str) -> int:
    """Size visible-output budget from source length, bounded for cost control."""
    estimated_source_tokens = max(1, (len(content) + 2) // 3)
    estimated_output_tokens = estimated_source_tokens * 2 + 1024
    return min(
        _TRANSLATE_MAX_TOKENS,
        max(_TRANSLATE_MIN_TOKENS, estimated_output_tokens),
    )


def translate_changelog(
    content: str,
    model: str = None,
    api_key: str = None
) -> str:
    """
    翻译更新日志内容

    Args:
        content: 要翻译的英文内容
        model: 模型名称，默认使用环境变量 LLM_MODEL
        api_key: API Key，默认使用环境变量 LLM_API_KEY

    Returns:
        str: 翻译后的中文内容，失败时返回空字符串
    """
    model = model or os.getenv("LLM_MODEL", "")
    api_key = api_key or os.getenv("LLM_API_KEY", "")

    if not model:
        print("LLM_MODEL 未设置，跳过翻译")
        return ""

    if not api_key:
        print("翻译配置未设置，跳过翻译")
        return ""

    cached = translation_cache.get(content, model, kind=_TRANSLATION_CACHE_KIND)
    if cached:
        print(f"翻译缓存命中 (跳过 LLM 调用, {len(cached)} 字符)")
        return cached

    try:
        document = protect(content)
    except ValueError as e:
        print(f"翻译失败: 无法保护原文 ({e})")
        return ""

    messages = [
        {"role": "system", "content": _TRANSLATION_SYSTEM_PROMPT},
        {"role": "user", "content": f"<SOURCE>\n{document.protected}\n</SOURCE>"},
    ]
    translation_max_tokens = _translation_max_tokens(content)
    print(f"翻译输出上限: {translation_max_tokens} tokens (reasoning effort: {_reasoning_effort()})")

    candidate = ""
    finish_reason = ""
    first_call_failed = False
    try:
        candidate, finish_reason = _request_completion(
            model=model,
            api_key=api_key,
            messages=messages,
            max_tokens=translation_max_tokens,
        )
    except Exception as e:
        print(f"翻译失败: {e}")
        if _is_fatal_error(e):
            print("翻译失败: 检测到致命错误，终止重试")
            return ""
        first_call_failed = True

    if finish_reason == "length":
        print("翻译失败: 输出达到 max_tokens，拒绝截断结果")
        return ""

    # 空内容或可重试异常只重试同一个完整请求一次。整个流程最多 3 次模型调用：
    # 首次翻译 + 一次完整重试 + 一次定向修复。
    full_retry_used = False
    if first_call_failed or not candidate:
        full_retry_used = True
        print("翻译返回空内容或临时失败，使用同一模型重试一次")
        try:
            candidate, finish_reason = _request_completion(
                model=model,
                api_key=api_key,
                messages=messages,
                max_tokens=translation_max_tokens,
            )
        except Exception as e:
            print(f"翻译失败: {e}")
            if _is_fatal_error(e):
                print("翻译失败: 检测到致命错误，终止重试")
            return ""
        if not candidate or finish_reason == "length":
            print(f"翻译失败: 第二次调用无有效内容 (finish_reason={finish_reason})")
            return ""

    candidate, validation = _validate_candidate(document, candidate)

    if not validation.valid and not _is_locally_repairable(validation) and not full_retry_used:
        print(f"翻译校验失败 ({', '.join(validation.reasons)})，使用同一模型完整重试一次")
        try:
            candidate, finish_reason = _request_completion(
                model=model,
                api_key=api_key,
                messages=messages,
                max_tokens=translation_max_tokens,
            )
        except Exception as e:
            print(f"翻译重试失败: {e}")
            return ""
        if not candidate or finish_reason == "length":
            print(f"翻译重试无有效内容 (finish_reason={finish_reason})")
            return ""
        candidate, validation = _validate_candidate(document, candidate)

    if not validation.valid and _is_locally_repairable(validation):
        print(
            f"翻译校验失败 ({', '.join(validation.reasons)})，"
            f"定向修复 {len(validation.affected_lines)} 个失败行"
        )
        repair_prompt = (
            "只修复以下失败行。返回一个 JSON 对象：key 是 line 数字，value 是修复后的完整行。"
            "不要输出 Markdown 代码围栏。必须逐字保留每个 [[KEEP_...]] placeholder："
            "补回 missing_placeholders 中的每一项，删除 extra_placeholders 中多出的重复。\n\n"
            + json.dumps(
                repair_items(document, candidate, validation),
                ensure_ascii=False,
            )
        )
        try:
            repaired_content, repair_finish_reason = _request_completion(
                model=model,
                api_key=api_key,
                messages=[
                    {"role": "system", "content": _TRANSLATION_SYSTEM_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ],
                max_tokens=_TRANSLATE_MIN_TOKENS,
                response_format={"type": "json_object"},
            )
            if not repaired_content or repair_finish_reason == "length":
                print("翻译修复失败: 返回空内容或输出被截断")
            else:
                repaired_candidate = apply_repair(
                    candidate,
                    validation.affected_lines,
                    repaired_content,
                )
                repaired_candidate, repaired_validation = _validate_candidate(
                    document, repaired_candidate
                )
                # 修复可能改坏原本正确的行，只在整体严格变好时才采用
                if repaired_validation.issue_count < validation.issue_count:
                    candidate, validation = repaired_candidate, repaired_validation
                else:
                    print(
                        f"翻译修复未改善 (修复后 {repaired_validation.issue_count} 处，"
                        f"修复前 {validation.issue_count} 处)，保留修复前结果"
                    )
        except Exception as e:
            print(f"翻译修复失败: {e}")

    if not validation.valid:
        print(f"翻译修复后仍未通过校验: {', '.join(validation.reasons)}")
        if not _accept_degraded(document, validation):
            return ""

    translated = restore(document, candidate)
    if not _check_translation_quality(translated):
        chinese_count = _count_chinese_chars(translated)
        chinese_ratio = chinese_count / len(translated) * 100 if translated else 0
        print(
            f"翻译质量不合格 (中文占比: {chinese_ratio:.1f}%，"
            f"要求 >= {MIN_CHINESE_RATIO * 100}%)"
        )
        return ""

    chinese_count = _count_chinese_chars(translated)
    chinese_ratio = chinese_count / len(translated) * 100
    print(f"翻译完成 (中文占比: {chinese_ratio:.1f}%)")
    translation_cache.set(
        content,
        model,
        translated,
        kind=_TRANSLATION_CACHE_KIND,
    )
    return translated


def summarize_changelog(
    content: str,
    model: str = None,
    api_key: str = None
) -> str:
    """
    生成简短的中英文更新要点总结，用于 Telegram 消息正文。

    Args:
        content: 英文更新内容
        model: 模型名称，默认使用环境变量 LLM_MODEL
        api_key: API Key，默认使用环境变量 LLM_API_KEY

    Returns:
        str: 英文要点 + 空行 + 中文要点，失败时返回空字符串
    """
    model = model or os.getenv("LLM_MODEL", "")
    api_key = api_key or os.getenv("LLM_API_KEY", "")

    if not model:
        print("LLM_MODEL 未设置，跳过总结生成")
        return ""

    if not api_key:
        print("翻译配置未设置，跳过总结生成")
        return ""

    cached = translation_cache.get(content, model, kind="summarize")
    if cached:
        print(f"摘要缓存命中 (跳过 LLM 调用, {len(cached)} 字符)")
        return cached

    # 超长输入截断：摘要只需要前面的 Highlights/Breaking/New Features 段落
    summarize_input = content
    if len(summarize_input) > _SUMMARIZE_INPUT_TRUNCATE_CHARS:
        print(
            f"摘要输入过长 ({len(summarize_input)} 字符)，截断到前 "
            f"{_SUMMARIZE_INPUT_TRUNCATE_CHARS} 字符以节省 token"
        )
        summarize_input = summarize_input[:_SUMMARIZE_INPUT_TRUNCATE_CHARS]

    summary_system = f"""Please extract 3-8 important updates from release notes and produce a concise bilingual summary.

Requirements:
- Output format: English bullet points first, then a blank line, then Chinese bullet points
- Each bullet point starts with "• "
- Add a bold header "*Key Updates:*" before English points and "*更新要点：*" before Chinese points
- Keep the total output under 2000 characters
- Focus on user-facing changes: new features, important bug fixes, breaking changes
- Skip minor internal changes, dependency bumps, and trivial fixes
- Keep each point to one line, concise and clear

{TERMINOLOGY_INSTRUCTION}

Example output format:
*Key Updates:*
• Added new feature X for better performance
• Fixed critical bug in Y component
• Breaking change: Z API now requires authentication

*更新要点：*
• 新增 X 功能以提升性能
• 修复 Y 组件中的关键错误
• 破坏性变更：Z API 现在需要认证

Only output the summary in the demonstrated format."""

    try:
        response = completion(
            model=model,
            api_key=api_key,
            messages=[
                {"role": "system", "content": summary_system},
                {"role": "user", "content": summarize_input},
            ],
            temperature=0.3,
            max_tokens=_SUMMARIZE_MAX_TOKENS,
            extra_body=_build_extra_body(),
        )
        if not response.choices or len(response.choices) == 0:
            print("总结生成失败: API 返回空结果")
            return ""

        choice = response.choices[0]
        if str(choice.finish_reason or "") == "length":
            print("总结生成失败: 输出达到 max_tokens")
            return ""
        summary = (choice.message.content or "").strip()
        if not summary:
            print("总结生成失败: API 返回空内容")
            return ""
        print(f"更新要点总结生成完成 ({len(summary)} 字符)")
        # 用原始 content 作为缓存键，避免截断后查不到
        translation_cache.set(content, model, summary, kind="summarize")
        return summary
    except Exception as e:
        print(f"总结生成失败: {e}")
        if _is_fatal_error(e):
            print("总结失败: 检测到致命错误（额度/credits/max_tokens），不再重试")
        return ""
