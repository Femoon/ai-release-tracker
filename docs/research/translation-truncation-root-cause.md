# OpenRouter + DeepSeek V4 Flash + LiteLLM 输出截断根因调查

> 调查日期：2026-08-19
> 症状：调用返回 `usage.completion_tokens == max_tokens`、`choice.finish_reason == "length"`，而 `choice.message.content` 为空或 `null`。
> 范围：只使用 OpenRouter、DeepSeek、LiteLLM 官方文档/源码和 OpenAI 官方兼容规范；未修改生产代码。另使用当前 `StreamLake` endpoint 做了两组最小 API 探针，未发送 Telegram 或生产 changelog。

## 结论摘要

最高概率是**输出预算被 thinking/reasoning 消耗完**：DeepSeek 官方文档说明 V4 Flash 的 thinking mode 默认开启且默认 effort 为 `high`；OpenRouter 说明 reasoning tokens 属于 output tokens，并会出现在独立的 `reasoning` 字段。若 `max_tokens` 的预算先被 reasoning 占满，模型可能在产生可见译文前达到上限，于是规范允许 `finish_reason="length"` 且 `message.content` 为 `null`。`completion_tokens == max_tokens` 是这个假设的强信号；本次最小探针进一步观察到默认请求的 `reasoning_tokens=80`，而显式 `reasoning.effort=none` 为 `0`，并在极小上限下复现了 `content=null` + `finish_reason=length`。

第二可能是译文本身（加上思考过程）确实超过了 `max_tokens`，或输入接近 provider 的上下文上限。第三可能是 OpenRouter 将同一模型 slug 路由到不同 provider，provider 对 thinking、参数和 token 上限的实现不同。LiteLLM 当前 OpenRouter transformation 会把 `max_tokens` 作为 OpenAI 参数传递，并将 provider 的 `content` 与 reasoning 分开解析；它会把上游的 `null` 通过本项目的 `content or ""` 变成空字符串，但没有证据表明 LiteLLM 自己制造了 `finish_reason="length"`。

## 证据链

### 1. OpenAI 兼容规范：`length` 与空 content 都是合法响应形状

OpenAI 官方 OpenAPI 规范的 `ChatCompletionResponseMessage.content` 类型是 `string | null`，因此客户端不能把 `null` 等同于“请求没有完成”：[官方规范](https://github.com/openai/openai-openapi/blob/master/openapi.yaml)（`ChatCompletionResponseMessage`）。

同一规范对 Chat Completion choice 的 `finish_reason` 定义为：`length` 表示“达到请求中指定的最大 token 数”；`content_filter` 才表示内容被过滤，`tool_calls` 表示调用了工具。[官方规范](https://github.com/openai/openai-openapi/blob/master/openapi.yaml#L33509-L33532)

规范的 JSON-mode 说明还明确说：当 `finish_reason="length"` 时，message content 可能被部分截断；原因是超过 `max_tokens` 或对话超过最大上下文长度。[官方规范](https://github.com/openai/openai-openapi/blob/master/openapi.yaml#L29089-L29099)

规范将 `completion_tokens` 定义为“generated completion 中的 token 数”，并提供 `completion_tokens_details.reasoning_tokens` 字段（reasoning 是模型生成的 token）。[官方规范](https://github.com/openai/openai-openapi/blob/master/openapi.yaml#L32210-L32248) 这支持把 token 用量与可见文字长度分开检查；OpenRouter 对 reasoning 是否计入 output 的说明更直接见下节。

### 2. OpenRouter：reasoning 计入 output；响应可同时暴露原始 finish reason

OpenRouter Reasoning Tokens 文档说明：reasoning tokens 是 output tokens，会计费；默认情况下若模型输出 reasoning，会放在每条 message 的 `reasoning` 字段。[Reasoning Tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens.md#reasoning-tokens)

OpenRouter 的参数文档定义 `max_tokens` 为模型响应生成 token 数的上限，且最大值受“上下文长度减 prompt 长度”限制；`max_completion_tokens` 具有相同的响应上限语义。[Parameters](https://openrouter.ai/docs/api_reference/parameters.md#max-tokens)

截至调查日的 V4 Flash endpoint API 也显示同一 slug 的后端并不统一：例如 Decart endpoint 为 `context_length=262144`、`max_completion_tokens=262144`，StreamLake 为 `1024000`/`384000`，DigitalOcean 的 `max_completion_tokens` 为 `null`，且量化标签分别为 fp4、fp8、unknown。[Endpoint API](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash-20260731/endpoints)

OpenRouter 的兼容响应 schema 中：

- `message.content` 是 `string | null`；
- 每个 choice 有规范化的 `finish_reason` 和 provider 原始的 `native_finish_reason`；
- 规范化 `finish_reason` 包括 `length`；原始原因应从 `native_finish_reason` 读取；
- 非流式响应带 `usage`，并可用响应 `id` 调用 `/api/v1/generation` 查询 token/cost/provider 统计；token 数使用模型原生 tokenizer。

来源：[OpenRouter API Overview](https://openrouter.ai/docs/api-reference/overview.md#completionsresponse-format)。

因此，现场必须保存 `native_finish_reason`、响应 `id` 和 `/api/v1/generation?id=...` 的完整统计；只记录 LiteLLM 映射后的 `finish_reason` 与 `content` 不足以定位 provider 行为。

### 3. DeepSeek：V4 Flash 默认 thinking，高 effort；reasoning 与 content 分离

DeepSeek 官方 Thinking Mode 文档对 V4 Flash/V4 Pro 给出以下行为：

- thinking mode 默认开启，默认 effort 为 `high`；
- OpenAI 格式可用 `reasoning_effort`，兼容格式可用 `thinking: {type: enabled/disabled}`；
- thinking mode 的链式思考通过 `reasoning_content` 返回，与最终 `content` 同级；
- thinking mode 不支持 `temperature`、`top_p`、presence/frequency penalty，这些参数即使传入也无效果。

来源：[DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)。

该文档的工具调用样例还展示了一个合法状态：中间 assistant 消息 `content=''`，但同时存在 `reasoning_content` 和 `tool_calls`。当前项目请求没有 `tools`，所以这个解释优先级较低，但仍应检查响应是否意外包含 `tool_calls`。

### 4. LiteLLM：参数透传和响应解析不会把 reasoning 自动变成译文

项目锁定 LiteLLM `1.80.10`。LiteLLM 的 OpenRouter transformation 源码（对应仓库 tag `v1.80.10-nightly` 的同一实现线）显示：

- `OpenrouterConfig` 继承 OpenAI Chat transformation；支持参数列表包含 `max_tokens` 和 `max_completion_tokens`；
- `transform_request()` 调用父类转换后将请求发往 OpenRouter，并补充 `usage: {include: true}`；
- `transform_response()` 调用父类标准 OpenAI response parser，没有重写 `finish_reason` 或 `message.content`。

来源：[LiteLLM OpenRouter transformation](https://github.com/BerriAI/litellm/blob/v1.80.10-nightly/litellm/llms/openrouter/chat/transformation.py)；[LiteLLM OpenAI Chat transformation](https://github.com/BerriAI/litellm/blob/v1.80.10-nightly/litellm/llms/openai/chat/gpt_transformation.py)。

父类 parser 将 provider 消息中的 reasoning 字段提取为 `reasoning_content`，并将可见 `content` 单独放入 `Message(content=...)`。因此 LiteLLM 预期会保留两个字段，不会因为有 reasoning 就把它当作译文返回。当前项目 `_request_completion()` 的 `choice.message.content or ""` 只是在本地把上游 `null`/空字符串统一成 `""`，会损失可观测性，但不是 `length` 的根因。

## 根因排序

| 排名 | 假设 | 依据 | 置信度 | 首要证伪方法 |
| --- | --- | --- | --- | --- |
| 1 | thinking/reasoning 消耗完 `max_tokens`，可见译文尚未开始或只生成了极少内容 | DeepSeek 默认 high thinking；OpenRouter 将 reasoning 算作 output；观察到 completion_tokens 恰好等于 max_tokens 且 finish=`length` | 高 | 查看 `message.reasoning`/`reasoning_content`、`usage.completion_tokens_details.reasoning_tokens` 或 OpenRouter generation 统计；同一 prompt 用 `thinking.disabled`/`reasoning.effort=none` 做 A/B |
| 2 | 可见译文本身（或译文 + reasoning）超过 `max_tokens` | OpenAI 规范把 `length` 定义为达到最大 token；OpenRouter 上限还受 prompt 长度和上下文限制 | 中高 | 记录 prompt_tokens、输入字符/token 估算、请求的两个 max 参数；将上限显著提高或按标题分块，比较 completion_tokens 与 finish reason |
| 3 | OpenRouter provider 路由差异导致 thinking/参数/token 预算实现不一致 | 默认按价格在多个 provider 间负载均衡并允许 fallback；V4 Flash endpoint 的 context/max completion、量化和 supported parameters 各不相同 | 中 | 固定 `provider.only`/`order`，记录实际 provider；比较 `native_finish_reason`、reasoning 字段和 usage；用 `/api/v1/generation` 追溯单次请求 |
| 4 | LiteLLM/应用层的可观测性掩盖了上游返回 | LiteLLM parser 保留 content 与 reasoning；应用的 `content or ""` 把 null 变空字符串 | 中（解释“看起来为空”，不解释 length） | 在 LiteLLM 返回后打印 `repr(message.content)`、`repr(message.reasoning_content)`、原始 response JSON；不要只打印 `content` |
| 5 | 合法的 tool-call 中间轮次，最终 content 为空 | DeepSeek 官方样例显示带 `tool_calls` 的中间消息 content 可为空 | 低（当前请求未传 tools） | 检查 `choice.message.tool_calls`、`finish_reason`/`native_finish_reason`；若非空，按工具调用协议继续轮次 |
| 6 | 内容过滤/拒答 | OpenAI 规范将此类停止标为 `content_filter`，不是 `length` | 很低 | 仅当 finish reason 实际为 `content_filter` 或响应带 refusal 时再调查 |

## 必须补采的字段

### 请求侧（LiteLLM 发出前的最终 JSON）

1. `model` 的完整值（包括 `openrouter/` 前缀是否被 LiteLLM 去除）。
2. `messages` 的 token 数/字符数，以及是否包含重复 system prompt、巨大 placeholder 或整篇 changelog。
3. `max_tokens`、`max_completion_tokens` 是否同时存在，最终数值是多少；不要只看 Python 调用参数。
4. `reasoning`、`reasoning_effort`、`thinking`、`include_reasoning` 是否被显式加入；LiteLLM 是否因为模型能力识别而改写它们。
5. `temperature`、`top_p`、`tools`、`tool_choice`、`stop`、`response_format`、`stream` 和 `provider` 路由偏好。

### 响应侧（保留原始 JSON，不要先转字符串）

1. `id`、`model`、`choices[0].finish_reason`、`choices[0].native_finish_reason`。
2. `choices[0].message.content` 的原始值（区分 `null`、`""` 和非空字符串）。
3. `choices[0].message.reasoning`、`reasoning_content`、`tool_calls`、`refusal` 及所有 provider-specific 字段。
4. `usage.prompt_tokens`、`completion_tokens`、`total_tokens`，以及 `completion_tokens_details`（尤其 `reasoning_tokens`、`text_tokens`，若 provider 返回）。
5. 响应 headers（request/generation id、provider 相关 header）和 `/api/v1/generation?id=<id>` 返回的 provider、native token/cost、finish 状态。

## 最小验证矩阵

对同一短 prompt 和同一长 changelog 各运行以下请求，固定 provider 后再比较：

| 变体 | 目的 | 预期判据 |
| --- | --- | --- |
| 当前请求（`max_tokens=16384`，不显式 reasoning） | 建立基线 | 记录是否复现 `completion_tokens=max_tokens` + `length` |
| 显式关闭 thinking（DeepSeek `thinking: {type: "disabled"}` 或 OpenRouter `reasoning.effort: "none"`，以 endpoint 支持为准） | 验证根因 1 | 若 content 恢复且 completion_tokens 大幅下降，reasoning 预算假设成立 |
| 保持 thinking，显著提高 max 输出上限 | 区分预算不足 | 若 finish 从 `length` 变 `stop` 且译文完整，说明是输出预算问题；同时比较 reasoning/text token 明细 |
| 固定一个 provider，再换另一个支持同样参数的 provider | 验证根因 3 | 只在某 provider 复现时，优先按 endpoint 能力/实现调查 |
| 短 prompt、无 placeholder、无 tools | 排除输入/工具干扰 | 若短 prompt 仍复现，输入长度不是主因；若只长文复现，优先检查上下文与输出估算 |

## 不能从现象直接推出的结论

- `finish_reason="length"` 不能单独证明“翻译文本太长”；它也可能是 reasoning 先消耗完同一个输出预算，或 prompt 使可用上下文/输出上限变小。
- `message.content == ""` 不能单独证明模型没有生成任何 token；必须同时查看 `content` 原始 null/空值、reasoning 字段、tool calls 和 usage 明细。
- LiteLLM 的 `content or ""` 会掩盖 null 与空字符串差异，但没有证据说明它会把非空 provider content 截成空。
- OpenRouter 模型 slug 不等于固定后端。未记录实际 provider 和 `native_finish_reason` 时，不应把一次结果归因于 DeepSeek 权重本身。

## 社区与官方项目 issue 的同类案例

以下材料是 GitHub issue/PR 中的工程报告，不是 OpenAI、OpenRouter 或 DeepSeek 的规范性承诺；它们用于判断症状是否有现实先例，并单独标出接口路径和验证边界。

### 高相关：Goose #11142 / #11145（OpenAI-compatible 本地服务）

- [Goose issue #11142](https://github.com/aaif-goose/goose/issues/11142)（2026-08-11，open）报告：开启 reasoning 的自定义 OpenAI-compatible provider 时，`reasoning_content` 与 `content` 共用一个 `max_tokens`；DeepSeek-V4-Flash、Nemotron、Qwen thinking 等模型可能把整个预算耗在 reasoning，最终 `finish_reason: "length"`、0 content tokens、用户看到空响应。issue 给出 4096 上限的复现描述和基准：reasoning 开启时 4096 → `length`/0 content；关闭 reasoning 或提高到 6144 后恢复 `stop`/可见内容。
- [Goose PR #11145](https://github.com/aaif-goose/goose/pull/11145)（open）按该 issue 实现 `max_tokens = content_budget + thinking_budget`，为 high/max effort 增加 16384 thinking budget，并保证至少 1024 content tokens；测试覆盖 reasoning on/off。该 PR 仍是社区工程方案，不能当成所有 provider 的官方规则，但它与本项目的三元组（预算等于上限、`length`、空 content）高度一致。

边界：该案例主要是 llama.cpp/vLLM/Ollama 的 OpenAI-compatible 路径，未证明 OpenRouter 的每个 endpoint 都采用完全相同的预算实现；它证明的是共享预算这一机制和症状确有可复现先例。

### 高相关：LiteLLM #35645（DeepSeek V4 Flash 的 Anthropic-compatible 路径）

[LiteLLM issue #35645](https://github.com/BerriAI/litellm/issues/35645)（2026-08-19 抓取时 open）报告了 DeepSeek V4 Flash 原生 Anthropic 路由的参数错配：LiteLLM 将 `output_config.effort` 翻译成 `thinking: {type: enabled, budget_tokens: N}`，但报告者称 DeepSeek Anthropic endpoint 忽略 `budget_tokens`。其长 prompt 复现记录为：`max_tokens=8000`、约 29,900 字符 reasoning、`usage.output_tokens=8000`、`stop_reason=max_tokens`、没有 text block。报告还称 `thinking: {type: disabled}` 能恢复正常。

这不是 OpenRouter Chat Completions 的直接复现，而且 issue 尚未被维护者确认；但它提供了两个需要在当前项目验证的具体风险：

1. 不要假定传入的 thinking budget 一定被 DeepSeek endpoint 执行；要用 provider 原始请求和 usage 验证。
2. 对 DeepSeek 的不同协议路径（OpenAI Chat、Anthropic Messages）分别做 A/B；“关闭 thinking 后恢复”是很强的因果信号。

相关 LiteLLM 官方项目 PR [#31465](https://github.com/BerriAI/litellm/pull/31465) 使用真实 DeepSeek API 测试了 `thinking={type: enabled}`、多个 `reasoning_effort` 和 `thinking={type: disabled}`；PR 声称 disabled 请求能成功且不再返回 reasoning。这是项目级测试记录，不等于 DeepSeek/OpenRouter 的服务保证，但支持把关闭 thinking 作为低风险诊断变体。

### 中相关：LiteLLM #27492（下游转换把非空回答变成空 content）

[LiteLLM issue #27492](https://github.com/BerriAI/litellm/issues/27492) 报告 Anthropic `/v1/messages` proxy 在上游同时返回 `content` 与 `reasoning_content` 时，转换结果可能出现 `content: []`；同一请求直接走 `/v1/chat/completions` 可得到 `content: "hello"` 和 `reasoning_content: "Thinking..."`。该案例把问题归因于 LiteLLM 的 Anthropic adapter，而不是 provider 截断。

对当前项目的意义：如果实际调用链经过 Anthropic-compatible proxy，必须同时抓取 proxy 前后的原始 JSON；但当前 `core/translate/llm.py` 直接调用 Chat Completions，故该 issue 更像排除项和观测提醒，而不是首要根因。

### 中相关：OpenRouter 官方 SDK 仓库 issues/PR

- [OpenRouter AI SDK issue #501](https://github.com/OpenRouterTeam/ai-sdk-provider/issues/501) 报告 DeepSeek V4 tool-call 续轮要求把上轮 assistant 的 `reasoning_content` 原样传回，否则 provider 返回错误；问题描述给出了 `reasoning`/`reasoning_details` 与 DeepSeek 所需 `reasoning_content` 的字段差异。
- [OpenRouter AI SDK PR #504](https://github.com/OpenRouterTeam/ai-sdk-provider/pull/504) 试图保留 DeepSeek 响应中的 `reasoning_content`，并在 tool-call history 中重放；说明 OpenRouter normalized `reasoning` 与 DeepSeek 原生字段并非始终一致。
- [OpenRouter AI SDK issue #426](https://github.com/OpenRouterTeam/ai-sdk-provider/issues/426)（closed）报告另一模型 Kimi 在约 19.5% 的生产消息中把最终答案全部放进 reasoning、`content` 为 0；其 `finish_reason` 是 `stop` 而非 `length`，因此不能用来证明本项目的截断根因，但说明下游只读取 content 会漏掉可见回答。

这些 SDK issue 不构成 OpenRouter 对 DeepSeek V4 Flash `max_tokens` 预算的官方承诺；它们强化了报告中“必须保存原始 `reasoning`/`reasoning_content`、`native_finish_reason` 和 provider 信息”的诊断要求。

### 未找到的直接证据

截至 2026-08-19，未找到 OpenRouter 官方 issue/announcement 明确承认“DeepSeek V4 Flash Chat Completions 在默认 reasoning 下必然把 `max_tokens` 全部分给 reasoning”这一固定行为，也未找到 DeepSeek 官方 issue 给出该症状的统一阈值。现有最强证据仍是官方文档的 token 语义，加上上述独立社区复现；生产结论必须以一次请求的原始 JSON 和 generation 统计为准。

## 一手来源

- [OpenAI OpenAPI 规范：ChatCompletionResponseMessage / Choice / CompletionUsage](https://github.com/openai/openai-openapi/blob/master/openapi.yaml)
- [OpenRouter API Overview：响应格式、native_finish_reason、generation 统计](https://openrouter.ai/docs/api-reference/overview.md)
- [OpenRouter Parameters：max_tokens / max_completion_tokens](https://openrouter.ai/docs/api_reference/parameters.md)
- [OpenRouter Reasoning Tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens.md)
- [OpenRouter Provider Routing](https://openrouter.ai/docs/guides/routing/provider-selection.md)
- [OpenRouter DeepSeek V4 Flash Endpoint API](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash-20260731/endpoints)
- [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)
- [LiteLLM OpenRouter transformation source](https://github.com/BerriAI/litellm/blob/v1.80.10-nightly/litellm/llms/openrouter/chat/transformation.py)
- [LiteLLM OpenAI Chat transformation source](https://github.com/BerriAI/litellm/blob/v1.80.10-nightly/litellm/llms/openai/chat/gpt_transformation.py)
- [Goose issue #11142：reasoning 与 content 共用 max_tokens](https://github.com/aaif-goose/goose/issues/11142)
- [Goose PR #11145：为 reasoning 预算补足 max_tokens](https://github.com/aaif-goose/goose/pull/11145)
- [LiteLLM issue #35645：DeepSeek V4 Flash budget_tokens 被忽略、无 text block](https://github.com/BerriAI/litellm/issues/35645)
- [LiteLLM PR #31465：DeepSeek disabled thinking 支持](https://github.com/BerriAI/litellm/pull/31465)
- [LiteLLM issue #27492：reasoning_content 导致 Anthropic adapter 丢 content](https://github.com/BerriAI/litellm/issues/27492)
- [OpenRouter AI SDK issue #501：DeepSeek tool-call 需要 reasoning_content](https://github.com/OpenRouterTeam/ai-sdk-provider/issues/501)
- [OpenRouter AI SDK PR #504：保留 DeepSeek reasoning_content](https://github.com/OpenRouterTeam/ai-sdk-provider/pull/504)
- [OpenRouter AI SDK issue #426：最终回答落入 reasoning、content 为空](https://github.com/OpenRouterTeam/ai-sdk-provider/issues/426)
