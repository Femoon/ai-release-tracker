# 历史翻译缺陷修复计划（2026-10-19）

来源：生产 checker 日志全量排查（2026-03 至今）。频道现状于 2026-10-19 实时读取 `t.me/s/<channel>` 和 Telegraph API 确认。

**状态：已于 2026-10-19 执行完毕，6/6 修复成功。** 6 个目标的翻译和摘要都一次通过质量检查；编辑后逐条读回，并检查了公开频道和页面的渲染效果。

## 范围

只修复已发布、但译文缺失或摘要缺失的内容，全部**原位编辑**：

- 不发送新消息，不删除消息，不补推。Claude Code 2.1.247 从未推送，按决定不处理。
- 不创建新的 Telegraph 页面。下列页面均已用生产 token 通过 `getPageList` 确认归本账号所有，可以 `editPage`，频道里的链接保持不变。
- 不读写 `output/` 下的版本记录和消息状态。这些都是历史版本，各产品当前的 `message_state` 已指向更新的版本，改动它们会干扰 checker。

| # | 版本 | 频道消息 | 现状 | 修复动作 |
|---|------|---------|------|---------|
| 1 | Claude Code 2.1.243 | `claude_code_push/579` | 消息有双语摘要；页面 `Claude-Code-21243-Release-Notes-08-25` 只有英文（中文 6 字） | 重新翻译，编辑页面 |
| 2 | OpenClaw 2026.4.25 | `openclaw_push/87` | 消息只有一行链接；页面 `OpenClaw-2026425-Release-Notes-EN-04-26-17` 只有英文 | 重新翻译，编辑页面；生成摘要，编辑消息 |
| 3 | OpenClaw 2026.4.26 | `openclaw_push/88` | 同上，页面 `OpenClaw-2026426-Release-Notes-EN-04-27-13` | 同上 |
| 4 | OpenClaw 2026.5.9 | `openclaw_push/95` | 消息有双语摘要；页面 `OpenClaw-202659-Release-Notes-EN-05-13-2` 只有英文 | 重新翻译，编辑页面 |
| 5 | OpenClaw 2026.6.11 | `openclaw_push/117` | 消息有双语摘要；页面 `OpenClaw-2026611-Release-Notes-06-30` 只有英文 | 重新翻译，编辑页面 |
| 6 | OpenClaw 2026.9.8 | `openclaw_push/128` | 页面已是双语（中文 1548 字）；消息是"Summary unavailable / 暂无摘要"降级通知 | 只生成摘要，编辑消息 |

## 原文来源（已离线验证，未调用 LLM）

按当前 checker 的规则筛选和裁剪，保证翻译和发布使用同一份原文：

| 版本 | 来源 | 原文 → 通知内容 | placeholder |
|------|------|----------------|-------------|
| 2.1.243 | 当前 `CHANGELOG.md` → `limit_notification_content` | 9,331 → 7,978 | 108 |
| 2026.4.25 | `fetch_release_changelog` → `select_notification_content` | 82,676 → 2,811 | 25 |
| 2026.4.26 | 同上 | 73,955 → 4,425 | 50 |
| 2026.5.9 | **上游 release 和 tag 都已不存在（404）**。改用 `CHANGELOG.md` 在 `9431d18`（2026-05-14 前最后一次提交）的版本，再走 `select_notification_content` | 95,169 → 7,956 | 138 |
| 2026.6.11 | `fetch_release_changelog` → `select_notification_content` | 105,722 → 7,950 | 76 |
| 2026.9.8 | 只需要摘要，输入与原通知相同 | 11,077 → 7,910 | — |

2026.5.9 的原文链接不能用 `release_url()`，因为它返回 404。改用固定到该 commit 的 `CHANGELOG.md` blob 链接。

## 修复后的内容

- **页面**：使用和现在 `publish_changelog` 单页模式相同的 HTML 结构（English → `<hr>` → 中文 → 原文链接）。正文从"完整英文"变成"裁剪后的双语内容 + 完整日志链接"，与现在新版本的推送一致。原来标题带 `(EN)` 的页面（#2–#4）把标题改成 `OpenClaw <version> Release Notes`。Telegraph 不能改 path，path 里的 `EN` 会保留。
- **消息**（#2、#3、#6）：沿用 `_telegraph_notification_message` 的格式：标题 + 双语摘要 + 原来的链接行。Telegraph URL 和 GitHub 链接与现有消息完全相同。
- 为了避免 HTML 拼装出现两套实现，先把 `publish_changelog` 里的 `_build_html` 提取成模块级函数，供修复脚本复用，checker 的行为不变。

## 实现：照现有 prepare / apply 两步走

### 1. `scripts/prepare_translation_repairs.py`（会调用 LLM，不修改线上内容）

对每个目标：

1. 按上表取原文、筛选、裁剪。
2. 调用 `translate_changelog`。现有质量门槛全部保留：placeholder 校验、中文占比检查、每个目标最多调用 3 次。不合格的目标在计划中标为 `failed`，**不降级为英文**。
3. 需要编辑消息的，调用 `summarize_changelog`（最多调用 2 次）。摘要失败的目标在计划中标为 `failed`，不再生成新的降级通知。
4. 读取页面当前内容和消息当前文本，作为 `before` 写入计划；同时写入 `after`、`sha256`，以及 Telegraph 和 Telegram 的长度检查结果。

产物：`output/channel-review/translation-repairs.json`，另外为每个目标生成一份便于人工审阅的 Markdown 对照。

LLM 调用上限：翻译 5 个目标 × 3 次 + 摘要 3 个目标 × 2 次，合计 ≤ 21 次。翻译缓存命中时会更少。

### 2. `scripts/apply_translation_repairs.py`（默认只校验，加 `--apply` 才写入）

做法沿用 `apply_article_repairs.py` / `repair_channel_history.py` 的保护措施：

- 编辑前再读一次当前内容。只有当前内容与计划里的 `before` 一致（或已经等于 `after`）时才编辑，避免覆盖期间的其他改动。
- 页面编辑使用 `edit_page`（不会退回到创建新页面），编辑后读回校验。
- 消息编辑使用 `edit_telegram_message`，按频道限速。消息只读取 `*_BOT_TOKEN`，不会发送新消息。
- 每个目标的结果写入 `output/channel-review/translation-repair-results/`。按 `sha256` 保证幂等，重跑会跳过已完成的目标。
- 支持 `--only <target>`，可以先修一个看效果。

## 执行步骤

1. 提取 `_build_html`，补单元测试（`unittest`，mock `core.translate.llm.completion`），运行全部测试。
2. 本地运行 prepare。LLM 配置必须与生产 `.env` 一致（`LLM_MODEL`、`LLM_PROVIDER_ONLY`、`LLM_REASONING_EFFORT`），否则译文质量与线上不一致。
3. **人工审阅**每个目标的对照文件。
4. 先 `apply --only openclaw_push/128` 试修一个最小目标（只改消息），检查频道显示效果。
5. 确认后执行其余目标的 `--apply`。
6. 用 `audit_channel_history.py` 重新快照，确认 6 个目标的中文内容和链接正常。

第 4、5 步会修改公开频道和 Telegraph 页面，执行前需要再次确认。

## 风险

- **页面正文变短**：#2–#5 原本是完整英文，修复后只保留裁剪后的内容，完整内容需要点原文链接查看。这与现在的推送规则一致；如果想保留完整英文，就必须翻译完整原文，这违反"翻译和发送使用同一份原文"，也超出 LLM 调用预算，不建议。
- **2026.5.9 的原文无法从上游 release 复核**：依赖历史 commit。审阅时需要与现有英文页 `-EN-05-13-2` 对照，确认是同一份内容。
- **GLM 偶发原样输出英文**：会被质量门槛拦下，该目标标为 `failed`，下次重跑 prepare 即可，不影响其他目标。

## 不在本计划内

- Claude Code 2.1.247 补推。
