# DeepSeek V4 Flash 0731 用于软件 Changelog 翻译的最佳实践

> 调研日期：2026-08-18
> 目标场景：通过 LiteLLM + OpenRouter，将 Claude Code 英文 changelog 翻译为中文，并严格保留指定专业术语、Markdown 结构和代码标识符。

## 结论摘要

`deepseek/deepseek-v4-flash-0731` 确实对应 DeepSeek 官方发布的 `DeepSeek-V4-Flash-0731`，不是第三方重命名模型。模型本身足以完成这类翻译；最近三个 Claude Code 版本出现的术语翻译问题，不足以证明模型指令遵从能力差，更直接的原因是当前系统把“术语必须保留”仅作为自然语言要求，却没有在调用前保护术语、在调用后逐项校验。

对当前任务，建议按以下优先级改进：

1. **程序化保护和校验术语**：调用前把术语、代码片段、命令、路径等替换为不可翻译占位符，调用后验证占位符数量和顺序并还原。这比继续堆叠 prompt 文案可靠。
2. **规则与原文分离**：固定规则和 glossary 放 `system` message，待翻译文本单独放 `user` message。
3. **关闭或避免复杂推理**：简单翻译不需要 `high`/`max` reasoning；不要为了“更听话”增加 reasoning effort。
4. **降低 provider 漂移**：OpenRouter 的同一模型 ID 当前由多家、不同量化的 endpoint 提供。若要求回归结果稳定，可固定 DeepSeek 官方 endpoint；若优先可用性，则保留多 provider 路由，但接受输出会有轻微漂移。
5. **用任务不变量验收，而不是只看中文占比**：检查列表项、标题、代码片段、URL、术语和占位符是否一一保留，并把三个已发现误译加入回归集。

## 模型身份与能力边界

- OpenRouter 模型 ID 是 `deepseek/deepseek-v4-flash-0731`，canonical slug 是 `deepseek/deepseek-v4-flash-20260731`，指向官方 Hugging Face 仓库 `deepseek-ai/DeepSeek-V4-Flash-0731`。[OpenRouter 模型目录](https://openrouter.ai/api/v1/models) [DeepSeek 官方模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- DeepSeek 将 0731 描述为 V4 Flash 的正式版本，取代 preview；模型为 sparse MoE，284B 总参数、13B active，并使用 MIT License。[DeepSeek 官方模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- 模型是纯文本 `text -> text`。OpenRouter 聚合元数据声明它支持常用采样参数、`response_format`、structured outputs、tools 和 reasoning；但模型级 `supported_parameters` 是各 endpoint 能力的并集，不代表每个 endpoint 都支持全部参数。[OpenRouter 模型目录](https://openrouter.ai/api/v1/models) [OpenRouter Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs.md)
- DeepSeek 官方 encoding 支持 `system`、`user`、`assistant`、`tool` 等角色。`developer` role 仅用于 DeepSeek 内部 search-agent pipeline，官方 API 不接受，因此当前翻译规则应使用 `system`，而不是 `developer`。[DeepSeek V4 Encoding](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/blob/main/encoding/README.md)
- 官方模型卡称 V4 系列支持百万 token 级上下文；OpenRouter 各 endpoint 公布的上下文窗口和最大输出并不一致。超大上下文说明模型“放得下”，不等于长输入下每条术语约束都能无损执行。[DeepSeek 官方模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731) [OpenRouter Endpoint API](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash-20260731/endpoints)

## 推荐调用参数

### Sampling

- 当前 `temperature=0.3` 是合理的确定性翻译基线，可以先保留。不要同时大幅调整 `temperature` 和 `top_p`，否则很难判断质量变化来自哪里。
- DeepSeek 的通用旧 API 指南曾为 Translation 推荐 `temperature=1.3`，但这不是 V4 Flash 0731 专属结论；V4 Flash 0731 模型卡对非 agent 场景建议 `temperature=1.0, top_p=1.0`。因此不应机械地把生产翻译从 `0.3` 改到 `1.3`，而应在固定回归集上对 `0.0/0.3/1.0` 做 A/B 测试，以术语、结构和语义错误率选值。[DeepSeek Temperature 指南](https://api-docs.deepseek.com/quick_start/parameter_settings) [DeepSeek 官方模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- 不建议为此任务设置 frequency/presence/repetition penalty。术语保留需要模型重复输入中的固定字符串，而惩罚重复可能适得其反。
- 如需更强复现性，可以测试固定 `seed`，但 OpenRouter 明确说明跨模型或 provider 不保证完全确定；固定 endpoint 比单独固定 seed 更重要。[OpenRouter Parameters](https://openrouter.ai/docs/api_reference/parameters.md)

### Reasoning

- DeepSeek V4 Flash 0731 支持 `low/high/max` reasoning effort。官方 agent/coding benchmark 使用 `max`，这是复杂 agent 任务设置，不是翻译建议。[DeepSeek 官方模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- 官方 encoding 说明 chat mode 不生成 reasoning，且 `reasoning_effort` 在 chat mode 无效；`high/max` 本质上会在 prompt 前加入要求详尽推理的强指令。简单翻译应使用 chat/non-thinking 路径或最低 effort，避免额外成本、延迟和过度改写。[DeepSeek V4 Encoding](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/blob/main/encoding/README.md)
- OpenRouter 当前模型元数据称 reasoning 默认启用、默认 effort 为 `high`，但项目锁定的 LiteLLM `1.80.10` 尚未把这个精确模型识别为 reasoning-capable，`get_supported_openai_params()` 也不返回 `reasoning_effort`。因此当前项目**不要重新加入** `reasoning_effort`；若未来要显式关闭 reasoning，应先升级/验证 LiteLLM 的实际请求体和 OpenRouter endpoint 行为。[OpenRouter Reasoning Tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens.md) [LiteLLM OpenRouter transformation](https://github.com/BerriAI/litellm/blob/main/litellm/llms/openrouter/chat/transformation.py)

### 输出长度

- `max_tokens` 是当前 LiteLLM/OpenRouter 调用可用的直接输出上限。不要同时传 `max_tokens` 和 `max_completion_tokens`。[LiteLLM Completion Input](https://docs.litellm.ai/docs/completion/input) [OpenRouter Parameters](https://openrouter.ai/docs/api_reference/parameters.md)
- 当前翻译固定给 `16384`，对最近约 8K 字符的 changelog 明显宽裕。更稳妥的生产策略是按输入 token 动态估算，例如“输入 token 的 1.5 倍 + 512”，设置合理上下限，并在 `finish_reason == "length"` 时用更大上限重试。这样既避免截断，也减少 OpenRouter 按声明输出上限做额度检查时的不必要失败。

### Structured output 与 prefill

- OpenRouter 的 structured outputs 是 **endpoint 级能力**。若使用 `json_schema`，应配合 `provider.require_parameters=true`，否则不支持的 provider 可能忽略参数。[OpenRouter Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs.md) [OpenRouter Provider Routing](https://openrouter.ai/docs/guides/routing/provider-selection.md)
- 当前项目的 LiteLLM `1.80.10` 对这个精确模型没有报告 strict response-schema 支持，而且最终产物本来就是 Markdown。为翻译再包一层 JSON 会引入转义、解析和 Markdown 还原风险，对术语保留没有直接收益，因此建议继续输出纯文本 Markdown。
- DeepSeek 官方 encoding 能表达历史 `assistant` message，但没有找到该 OpenRouter 模型 endpoint 对“assistant prefill/续写前缀”的正式保证。不要把 prefill 当作术语控制方案。
- 不建议启用 LiteLLM 的全局 `drop_params=True`。它会掩盖错误参数；固定单模型任务应只传经过确认的参数，让不兼容尽早失败。[LiteLLM Drop Unsupported Params](https://docs.litellm.ai/docs/completion/drop_params)

## Prompt 与术语保护设计

### Prompt 分层

固定 system message 只包含长期规则：

1. 角色：技术文档翻译器；只输出译文。
2. 不变量：标题、列表项数量和顺序、Markdown、代码块、行内代码、URL、用户名、命令和版本号不可改变。
3. 术语策略：区分“原样保留”和“固定译法”，不要把两类词混成一句自然语言说明。
4. 自检要求：输出前检查所有保护占位符恰好出现一次且顺序不变。

user message 只放清晰分隔的原文，例如 `<SOURCE>...</SOURCE>`。避免把任意 changelog 内容拼进 system message，也避免让模型判断原文中的句子是不是新指令。

Few-shot 示例应覆盖真正失败的边界，而不是只有 `Added -> 新增` 这类简单例子，例如：

- `auto mode`、`Subagent`、`Sandbox`、`Remote Control` 原样保留；
- `context cost` 按固定译法写作“上下文开销”；
- `newer models` 写作“更新的模型”，不能写成“更新型号”；
- `full-strength redaction` 写作“完整强度脱敏”或经维护者确认的固定译法，不能让模型自由猜测。

### 最可靠的术语方案：保护、验证、还原

单靠 prompt 中的 glossary 是软约束。生产上应采用以下流程：

1. 解析 Markdown，先保护代码块、行内代码、URL、命令、路径、环境变量和 GitHub 用户名。
2. 对“必须原样保留”的 glossary 进行最长匹配优先、大小写敏感替换，生成碰撞概率极低的占位符，例如 `⟦KEEP_0001_A7F3⟧`。
3. 将占位符与翻译规则一同发给模型，要求逐项原样复制。
4. 返回后比较输入与输出的占位符 multiset、数量和顺序；缺失、重复、变形或重排即判失败，不写缓存、不推送。
5. 校验通过后才还原原始术语。

这能把“模型通常会遵守”变为“只有满足保留约束的结果才能进入下游”。对于需要固定中文译法但不要求保留英文的短语，应维护单独的 bilingual glossary，并在回归测试中验证译法；不要简单做全局中文后处理，以免替换到错误语境。

## 对当前项目的具体判断

当前 `core/translate/llm.py` 已有较完整的 glossary、结构要求和 `temperature=0.3`，说明问题不是“完全没有提示”。但实现还有四个关键缺口：

1. 所有规则和原文都在同一条 `user` message，未利用模型官方支持的 `system` 角色分隔稳定约束。
2. `_check_translation_quality()` 只检查中文字符比例。它无法发现 `auto mode -> 自动模式`、`Sandbox -> 沙箱`、`newer models -> 更新型号` 或术语缺失。
3. 缓存键只有 `kind + model + source_text`，不含 prompt/glossary 版本。修改术语规则后，同一模型和原文仍会命中旧的不合格译文。
4. 默认 OpenRouter 路由可能把同一 model ID 发往不同 provider；当前 endpoint 列表包含 FP4、FP8、BF16 和 unknown quantization，实现漂移会降低回归可复现性。[OpenRouter Endpoint API](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash-20260731/endpoints)

最近三个 Claude Code 样本显示：列表项和反引号代码完整性很好，说明模型可胜任主体翻译；失败集中在术语分类和少数语义表达：

| 原文/术语 | 已观察问题 | 建议约束 |
| --- | --- | --- |
| `auto mode` | “自动模式” | 原样保护 |
| `Subagent` | “子代理” | 原样保护 |
| `Plugin marketplace` | “插件市场” | 若视为产品术语则原样保护，并统一大小写规则 |
| `Sandbox` | “沙箱” | 原样保护 |
| `Remote Control` | 部分译为“远程控制” | 原样保护 |
| `Skill` / `Permission` / `Prompt` | 多处被翻译 | 按 Claude Code 语境原样保护；其他语境用明确规则区分 |
| `context cost` | “环境成本” | 固定译为“上下文开销” |
| `full-strength redaction` | “全强度编辑下进行遮蔽” | 加入固定译法回归用例 |
| `newer models` | “更新型号” | 回归断言为“更新的模型” |

## 路由稳定性选择

OpenRouter 默认综合价格和 uptime 在 provider 间负载均衡，并允许 provider fallback；同一模型 ID 不代表同一服务实现。[OpenRouter Provider Routing](https://openrouter.ai/docs/guides/routing/provider-selection.md)

- **质量一致性优先**：在验收和生产中使用 `provider.only=["deepseek"]`，必要时关闭 provider fallback。优点是固定 DeepSeek 官方 FP8 endpoint；代价是价格可能更高、可用性下降。
- **可用性优先**：保留默认多 provider 路由，但设置 `provider.require_parameters=true` 以确保显式参数不会被静默忽略，并把术语/结构 validator 作为最终质量闸门。
- 两种方案都仍只使用 `deepseek/deepseek-v4-flash-0731` 这一个模型；区别只是该模型由哪个 endpoint 托管，不涉及第二模型 fallback。

## 对抗性复审：同模型定向二次修复是不是最佳实践

### 明确结论

“程序校验失败后，只让同一个 LLM 对失败片段做一次定向修复，再重新程序校验”是适合本项目的**有界恢复策略**，但不能表述为术语控制本身的社区最佳实践，也不能替代 placeholder、no-translate 或 exact validator。

主流机器翻译和本地化体系的共同基线是：翻译前用 glossary、不可翻译标记或 placeholder 明确约束，翻译后用程序检查占位符、格式说明符和结构完整性。DeepL、Amazon Translate、Google Cloud Translation 和 Azure Translator 都提供术语控制机制，但这些机制各有适用范围；其中 Amazon 还明确说明 custom terminology 不保证每次采用指定目标术语。对于必须逐字保留的字符串，官方文档更倾向于 `translate="no"`、`class="notranslate"`、XML/HTML placeholder 或 XLIFF inline code，而不是依赖自然语言提示。[DeepL Placeholder Tags](https://developers.deepl.com/docs/learning-how-tos/examples-and-guides/placeholder-tags) [Amazon Custom Terminology Best Practices](https://docs.aws.amazon.com/translate/latest/dg/ct-best-practices.html) [Google Cloud Translation Troubleshooting](https://cloud.google.com/translate/troubleshooting) [XLIFF 2.1](https://docs.oasis-open.org/xliff/xliff-core/v2.1/os/xliff-core-v2.1-os.html)

因此，更准确的工程表述是：**placeholder + deterministic validation 是主要保障；same-LLM repair 是只在失败路径启用的补救动作。** 当前没有找到一手资料证明“让同一个模型修复自己的译文”比重新生成失败片段、独立审校或人工复核更优。

### 证据等级

| 等级 | 能支持的结论 | 不能过度推导的内容 |
| --- | --- | --- |
| A：产品文档与开放规范 | glossary、no-translate、placeholder、XLIFF inline code 和格式校验是成熟机制 | 不能据此声称任意 LLM retry 都能可靠修复语义 |
| B：厂商评测与工程指导 | 生成模型有非确定性；明确 pass/fail 条件应优先使用代码校验；LLM grader 需要人工标注校准 | 不能把一次自动通过等同于长期质量保证 |
| C：本项目工程推断 | 一次、局部、可复验的同模型修复可降低偶发失败率，同时满足“始终只用一个模型” | 没有证据证明同模型修复是行业标准，或一定优于局部重新翻译 |

OpenAI 的评测指南建议把可机械判断的条件交给 metric/code eval，并持续运行回归评测；其 grader 文档也把 string check 用于明确的 pass/fail，同时警告 model grader 需要人工 ground truth 验证。Structured Outputs 只能保证 schema 形状，不能保证字段内容和术语语义正确。这些原则支持“程序负责硬约束、模型负责语言质量”，但并不直接为 same-LLM repair 提供保证。[OpenAI Evaluation Best Practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) [OpenAI Graders](https://developers.openai.com/api/docs/guides/graders) [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

### 产业基线与方案比较

| 方案 | 确定性 | 对当前任务的作用 | 建议 |
| --- | --- | --- | --- |
| Prompt 中列术语 | 低 | 提供翻译偏好和上下文 | 保留，但不作为质量闸门 |
| Glossary / 固定译法表 | 中 | 统一应翻译术语的中文译法 | 用于 `context cost` 等固定译法，不用于逐字符冻结 |
| Placeholder / no-translate | 高 | 保护代码、命令、路径、URL 和必须保留的英文术语 | 作为主机制 |
| 程序 validator | 高 | 检查占位符 multiset、顺序、Markdown 和术语不变量 | 作为放行条件 |
| 同模型定向修复 | 低到中 | 修复偶发遗漏或局部语义问题 | 最多一次，只处理失败列表项 |
| 第二模型审校 | 仍非确定性 | 可提供不同判断，但违反当前单模型要求 | 不采用 |
| 人工复核 | 高但有成本 | 处理歧义、语义质量和自动检查误报 | 作为非自动推送场景的最终出口 |

DeepL 官方 placeholder 示例直接采用“调用前替换为带唯一 ID 的标签，翻译后解析并还原”的流程。XLIFF 2.1 使用 `<ph>`、`<pc>`、`canCopy`、`canDelete` 和 `canReorder` 把不可翻译内容当成结构数据；GNU gettext 的 `msgfmt --check-format` 则检查源文和译文的格式说明符数量与类型。这些都说明，成熟实践的核心是保护和验证，而不是让翻译器自行记住每个硬约束。[DeepL Translating XML](https://developers.deepl.com/docs/translate/translating-xml) [GNU gettext `msgfmt`](https://www.gnu.org/software/gettext/manual/html_node/msgfmt-Invocation.html)

### 同模型修复的风险与反例

同一个模型拿到“原文 + 当前译文 + 违规项”后，通常能修复简单遗漏，但仍可能共享第一次调用的理解盲点，而且每次生成都具有非确定性。这里不应使用“确认偏差”作为已被直接证明的结论，更准确的风险描述是：第二次调用可能修好一个术语，同时改坏已经正确的语义、列表结构、其他术语或 Markdown。

典型反例包括：

- Validator 发现 `Sandbox` 被译成“沙箱”，模型修复整篇时又把已保留的 `Remote Control` 翻译掉。
- 模型为满足“补回缺失术语”，机械插入英文字符串，造成中文语义重复或放错位置。
- 只检查术语集合而不检查顺序时，二次输出包含所有术语却对应到错误列表项。
- 自由编辑整篇 changelog 时，模型重新组织句子，导致列表项合并、代码块边界变化或 URL 标点被吞入。
- Validator 本身误报时，二次修复会把本来正确的译文改坏。W3C ITS 2.0 明确指出，自动发现的 localization quality issue 不一定是真实错误，仍可能需要 review 确认。[W3C ITS 2.0](https://www.w3.org/TR/its20/)

所以修复请求必须提供机器检测到的精确差异，只重做受影响的完整列表项，不能要求模型“全面润色”或重写整篇。

### 本项目推荐状态机

1. **Protect**：解析 Markdown，把代码块、行内代码、URL、命令、路径、环境变量、用户名和必须保留术语替换为唯一 placeholder。
2. **Translate**：只调用 `openrouter/deepseek/deepseek-v4-flash-0731` 一次，按完整标题或列表项分块翻译。
3. **Validate**：程序检查 placeholder 的 ID、multiset、顺序和重复情况，并检查 Markdown 结构、列表项数量、代码、URL、版本号和固定译法。
4. **Accept**：全部通过后确定性还原 placeholder，写入缓存并允许推送。
5. **Repair once**：仅对失败的完整列表项再次调用同一个模型；输入包含原文、当前译文和 validator 给出的精确违规项，不改动其他已通过内容。
6. **Revalidate all**：对修复后的完整结果重新运行全部 validator，而不是只检查刚才失败的术语。
7. **Fail closed**：仍失败则不写缓存、不推送中文；保留英文通知或进入人工复核。禁止无限重试，也禁止切换到第二个模型。

这套状态机同时满足两个目标：正常路径只有一次模型调用；失败路径仍始终使用同一个模型，并把不可验证的生成行为限制在一个局部、一次性的恢复步骤内。

### 放行与失败标准

可以自动放行的结果必须同时满足：

- 所有 placeholder 的 ID、数量、顺序与源文一致，且还原后原字符串逐字一致。
- Markdown 标题、列表项数量和顺序、代码块、行内代码、URL、命令、路径及版本号保持不变。
- “必须原样保留”术语未被翻译；“固定中文译法”术语命中维护的 bilingual glossary。
- 输出非空、没有 `finish_reason == "length"`，且没有拒答、解释文字或额外前后缀。
- 修复路径已经对完整结果重新执行全部校验，而不是只验证单个差异。

以下任一情况必须失败关闭：placeholder 缺失、重复、变形或重排；结构不一致；受保护字符串变化；固定译法冲突；输出截断；一次修复后仍不通过。语义是否自然不能只靠字符串检查判断，最近三个 Claude Code 日志仍应作为人工标注的回归集，持续记录明显误译和术语边界。

## 建议验收方案

1. 固定最近三个 Claude Code changelog 为回归集，另增加包含 glossary 所有术语的最小合成样本。
2. 对 `temperature=0.0/0.3/1.0` 各运行至少 3 次；分别记录术语违规数、列表项/标题差异数、代码片段差异数、明显语义错误数和成本/延迟。
3. 必须满足：所有保护占位符数量和顺序一致；代码块、行内代码、URL、命令和版本号逐字一致；标题与列表项数量和顺序一致。
4. 必须覆盖已观察错误：`auto mode`、`Subagent`、`Sandbox`、`Remote Control`、`context cost`、`full-strength redaction`、`newer models`。
5. prompt 或 glossary 变化时更新显式版本号，并将该版本纳入缓存键；旧缓存不得参与新版本验收。
6. 记录 OpenRouter 响应中的实际 provider/endpoint 信息。若同一参数在不同 endpoint 的误差明显，决定是固定 DeepSeek endpoint，还是保留 provider fallback；无论哪种路由都不得切换到第二个模型。
7. 故意构造 placeholder 缺失、术语误译、列表项合并和输出截断用例，验证只有失败项会触发一次同模型修复，二次失败时会停止而不是继续循环。

## 最终建议配置

在不立即大改架构的前提下，推荐的基线是：

- 模型：`openrouter/deepseek/deepseek-v4-flash-0731`
- 消息：`system` 放规则和 glossary，`user` 仅放 source
- Sampling：先保留 `temperature=0.3`，不额外设置 sampling penalties；用回归测试决定是否调整到 `0.0` 或 `1.0`
- Reasoning：不传 `reasoning_effort`，不为简单翻译启用 high/max
- 输出：纯 Markdown，不启用 JSON schema/prefill
- 长文本：按 Markdown 标题和完整列表项分块，而不是按字符硬切；每块独立校验后按原顺序拼接
- 术语：程序化占位符保护 + exact validator + 还原
- 修复：仅 validator 失败时，让同一个模型对失败列表项定向修复一次；随后全量复验，再失败则关闭中文推送
- 缓存：缓存键加入 prompt/glossary 版本
- 路由：验收阶段固定 `deepseek` 官方 endpoint；生产是否允许同模型的 provider fallback 由可用性目标决定，不配置第二模型 fallback

这套方案的核心不是让模型“再认真一点”，而是把翻译任务中可机械判断的要求从 prompt 移到程序化约束里。模型负责语言质量，程序负责保证术语和结构不被破坏。

## 主要来源

- [DeepSeek-V4-Flash-0731 官方模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- [DeepSeek V4 官方 Encoding 说明](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/blob/main/encoding/README.md)
- [DeepSeek V4 Technical Report](https://arxiv.org/abs/2606.19348)
- [DeepSeek API Temperature 指南](https://api-docs.deepseek.com/quick_start/parameter_settings)
- [OpenRouter 模型目录 API](https://openrouter.ai/api/v1/models)
- [OpenRouter DeepSeek V4 Flash Endpoint API](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash-20260731/endpoints)
- [OpenRouter Parameters](https://openrouter.ai/docs/api_reference/parameters.md)
- [OpenRouter Provider Routing](https://openrouter.ai/docs/guides/routing/provider-selection.md)
- [OpenRouter Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs.md)
- [OpenRouter Reasoning Tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens.md)
- [LiteLLM OpenRouter Provider](https://docs.litellm.ai/docs/providers/openrouter)
- [LiteLLM Completion Input](https://docs.litellm.ai/docs/completion/input)
- [LiteLLM JSON Mode](https://docs.litellm.ai/docs/completion/json_mode)
- [LiteLLM Drop Unsupported Params](https://docs.litellm.ai/docs/completion/drop_params)
- [LiteLLM OpenRouter transformation source](https://github.com/BerriAI/litellm/blob/main/litellm/llms/openrouter/chat/transformation.py)
- [DeepL Placeholder Tags](https://developers.deepl.com/docs/learning-how-tos/examples-and-guides/placeholder-tags)
- [DeepL Translating XML](https://developers.deepl.com/docs/translate/translating-xml)
- [DeepL Glossaries](https://developers.deepl.com/docs/customize/managing-glossaries)
- [Amazon Translate Custom Terminology](https://docs.aws.amazon.com/translate/latest/dg/how-custom-terminology.html)
- [Amazon Translate Custom Terminology Best Practices](https://docs.aws.amazon.com/translate/latest/dg/ct-best-practices.html)
- [Amazon Translate Do-Not-Translate Tags](https://docs.aws.amazon.com/translate/latest/dg/customizing-translations-tags.html)
- [Google Cloud Translation Glossaries](https://cloud.google.com/translate/docs/advanced/glossary)
- [Google Cloud Translation Troubleshooting](https://cloud.google.com/translate/troubleshooting)
- [Azure Translator Dynamic Dictionary](https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/how-to/use-dynamic-dictionary)
- [OASIS XLIFF 2.1](https://docs.oasis-open.org/xliff/xliff-core/v2.1/os/xliff-core-v2.1-os.html)
- [GNU gettext `msgfmt`](https://www.gnu.org/software/gettext/manual/html_node/msgfmt-Invocation.html)
- [W3C Internationalization Tag Set 2.0](https://www.w3.org/TR/its20/)
- [OpenAI Evaluation Best Practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- [OpenAI Graders](https://developers.openai.com/api/docs/guides/graders)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
