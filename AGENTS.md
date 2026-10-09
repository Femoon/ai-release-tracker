# AGENTS.md

本文件为在此仓库中工作的编码 agent 提供指引。面向用户的安装说明见 `README.md` / `README_CN.md`。

## 项目概述

监控 AI 编码工具（Claude Code、OpenAI Codex、OpenClaw、Hermes Agent）的新版本发布，
将更新日志翻译成中文后推送到 Telegram 公开频道。Python >= 3.14，使用 uv 管理依赖。

```
main.py              依次以子进程运行 4 个 checker，任一失败则非零退出
core/
  notify/            telegram.py（双语消息、编辑）、telegraph.py（长文发布）
  translate/         llm.py（翻译与摘要）、policy.py（placeholder 保护与校验）、cache.py
  state/             message_state.py（已发送消息 ID、内容 hash、编辑次数）
  utils/             clean.py（release body 清洗）、content.py（通知内容裁剪）
products/<name>/
  checker.py         定时检查最新版本并推送（生产入口）
  pusher.py          手动批量补推历史版本
  fetcher.py         导出全部版本到 output/（codex、openclaw）
  其他               产品专属的数据源与内容筛选（releases.py、source.py、content.py）
output/              运行时状态与翻译缓存，不入库
```

## 常用命令

```bash
uv sync                                           # 安装依赖
uv run python -m unittest discover -s tests       # 运行全部测试
uv run python main.py                             # 检查所有产品

uv run python products/<name>/checker.py          # 检查单个产品
uv run python products/<name>/checker.py --force  # 强制推送最新版本，不更新记录
uv run python products/<name>/checker.py --force -V <version>  # 强制推送指定版本（hermes 不支持 -V）

uv run python products/<name>/pusher.py           # 补推未推送的历史版本，默认 3 个
uv run python products/<name>/pusher.py --count 5 / --all
uv run python products/hermes/pusher.py --dry-run --all   # 只检查裁剪结果，不翻译不发送
uv run python products/hermes/pusher.py --tag <tag> / --edit-tag <tag> / --edit-all
```

`codex/pusher.py` 读取 `output/codex_releases.txt`，需先运行 `codex/fetcher.py`。

**`--force` 和 pusher 会真实发送到配置的频道。** 本地 `.env` 若配置了生产 bot，
测试时先清空对应的 `*_BOT_TOKEN`，或只调用翻译函数而不走发送路径。

## 数据流

checker 流程：获取最新稳定版本 → 与 `output/<name>_latest_version.txt` 比对 →
按产品规则筛选内容并裁剪 → 翻译 → 发送 Telegram（超长则发布 Telegraph）→
**发送成功后**才写入版本记录和消息状态。

| 产品 | 数据源 | 稳定版判定 |
|------|--------|-----------|
| Claude Code | GitHub raw `CHANGELOG.md` | CHANGELOG 中最新的 `## x.y.z` |
| Codex | Releases Atom feed，逐个用 Releases API 校验 | 仅 `rust-vX.Y.Z` 且非 draft/prerelease；按版本号而非发布顺序取最大 |
| OpenClaw | Releases API；拆分的 `CHANGELOG/<version>.md` | 已发布、非 prerelease；内容标为 unreleased/beta 时拒绝 |
| Hermes | Releases API（Atom 备用） | 稳定 CalVer tag |

已发送版本若 release notes 后续变化，checker 会原位编辑已有消息，每个版本最多编辑
`MAX_EDITS_PER_VERSION` 次（`core/state/message_state.py`）。

## 不变量与约定

修改相关代码时必须保持：

- **状态只在成功后推进。** 翻译失败、Telegraph 发布失败或 Telegram 发送失败时，不写版本记录，
  由下一轮 cron 重试。回退或误写状态会导致公开频道重复推送。
- **翻译和发送使用同一份原文。** 先按产品规则筛选，再用 `limit_notification_content` 裁剪到
  8,000 字符以内（Claude Code、Codex、OpenClaw 按 Markdown 块边界裁剪并附原文链接；
  Hermes 使用自己的 Highlights 裁剪）。
- **翻译质量门槛不放松。** 译文需通过 placeholder 校验和中文占比检查；不合格时宁可不发送，
  也不推送英文或残缺译文。
- **LLM 调用次数有上限。** 翻译最多 3 次调用（首次 + 一次完整重试 + 一次定向修复）；
  长通知摘要最多 2 次。openai SDK 的自动重试保持关闭（`max_retries=0`），不要增加重试层。
- **摘要不是发布前提。** 两次都失败时照常发布 Telegraph，发送标明
  "Summary unavailable / 暂无摘要"并附完整日志链接的降级通知。降级通知不会自动补摘要；
  需要补时原位编辑已有消息，不要重新推送。
- **重量级依赖延迟导入。** 不要在模块顶层导入 `openai`；无新版本的检查轮次不应加载它。
  生产机器较慢，顶层导入会让每轮检查多出数秒。
- **`output/` 不入库**，包括版本记录、推送状态和翻译缓存。
- 测试使用 `unittest`，LLM 调用通过 `patch("core.translate.llm.completion")` mock。

## 配置

所有环境变量及示例值见 `.env.example`。首次运行（无版本记录）只写入当前版本，不推送。

| 变量 | 用途 | 未配置时 |
|------|------|---------|
| `<PRODUCT>_BOT_TOKEN` / `<PRODUCT>_CHAT_ID` | 各产品的 Telegram bot 与频道（`CLAUDE_CODE`、`CODEX`、`OPENCLAW`、`HERMES`） | Hermes 跳过翻译和通知；其他产品发现新版本时发送失败、不推进状态、checker 非零退出 |
| `LLM_API_KEY` / `LLM_MODEL` | 翻译模型。`LLM_MODEL` 沿用 `openrouter/<vendor>/<model>` 写法，发送时去掉 `openrouter/` 前缀 | 视为翻译失败：不推送英文原文、不推进状态、checker 非零退出 |
| `LLM_BASE_URL` | OpenAI 兼容端点，默认 OpenRouter | — |
| `LLM_PROVIDER_ONLY` | 固定 OpenRouter provider（逗号分隔），降低翻译质量方差 | 不限制路由 |
| `LLM_REASONING_EFFORT` | 默认 `none`；强制思考的模型（如 GLM）需设为 `minimal` | — |
| `LLM_TIMEOUT` | 单次 LLM 请求超时秒数，默认 300 | — |
| `TELEGRAPH_ACCESS_TOKEN` | 超过 Telegram 4,096 字符时发布长文 | 超长消息发送失败 |
| `TELEGRAPH_AUTHOR_NAME` / `TELEGRAPH_AUTHOR_URL` | Telegraph 文章署名 | 使用默认署名 |
| `GH_TOKEN` | GitHub API 认证（Codex、OpenClaw、Hermes），速率上限 60 → 5,000 次/小时 | 匿名访问，易被限流 |

`LLM_PROVIDER_ONLY` 和 reasoning 参数是 OpenRouter 扩展，换用其他端点时需按对方文档调整。
不要使用 `GITHUB_TOKEN` 作为变量名（GitHub Actions 保留变量）。

公开频道：[Claude Code](https://t.me/claude_code_push)、[OpenAI Codex](https://t.me/codex_push)、
[OpenClaw](https://t.me/openclaw_push)；Hermes Agent 暂未配置频道。

## 生产环境与部署

- 生产主机、路径、日志位置等环境细节记录在 `AGENTS.local.md`（不入库）。若该文件存在，
  执行部署或排查生产问题前先阅读它。生产环境细节只写入该文件，不要写进本文件、docs 或提交信息。
- 生产以 Docker 运行：宿主机 cron 每 30 分钟执行 `docker compose build` 和
  `docker compose run --rm version-checker`，外层用 `flock` 防止重叠；
  状态通过 `./output:/app/output` 持久化，配置来自服务器上的 `.env`。
- 部署使用 `scripts/deploy.sh`：运行测试 → rsync 同步代码 → 重建镜像并验证导入。
  目标读取自 `.deploy.env`（不入库，参考 `.deploy.env.example`）。可先用 `--dry-run` 核对同步列表。
- 服务器目录不是 git 仓库，不要在服务器上直接修改代码。部署必须保留服务器的 `.env` 和 `output/`。
- 本地修改不等于生产已部署。

## GitHub Actions

`.github/workflows/version-check.yml` 已在 GitHub 上手动停用，生产只依赖服务器 cron。
该 workflow 会把 `output/` 变更提交回仓库，与"`output/` 不入库"冲突；重新启用前需先改造状态持久化方式。
