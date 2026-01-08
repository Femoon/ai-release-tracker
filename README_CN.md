# AI Release Tracker

<div align="center">

[![][claude-code-shield]][claude-code-link]
[![][codex-shield]][codex-link]

</div>

AI 编码工具版本更新监控工具。自动检查新版本发布，并发送双语通知（英文 + 中文）到 Telegram。

[English](README.md)

<!-- Links & Images -->
[claude-code-shield]: https://img.shields.io/badge/Telegram-@claude__code__push-0088CC?logo=telegram
[claude-code-link]: https://t.me/claude_code_push
[codex-shield]: https://img.shields.io/badge/Telegram-@codex__push-0088CC?logo=telegram
[codex-link]: https://t.me/codex_push

## 功能特性

- 监控多个 AI 编码工具的版本更新
- 从 GitHub 解析更新日志（CHANGELOG.md 或 Atom feed）
- 使用 LiteLLM 进行 AI 翻译（支持多种 provider）
- 双语 Telegram 通知
- GitHub Actions 每 30 分钟自动检查
- 支持 Docker 部署

## 支持的工具

| 工具 | 脚本 | 数据源 | Telegram |
|------|------|--------|----------|
| Claude Code | products/claude_code/checker.py | GitHub CHANGELOG.md | [@claude_code_push](https://t.me/claude_code_push) |
| OpenAI Codex | products/codex/checker.py | GitHub releases Atom feed | [@codex_push](https://t.me/codex_push) |

## 快速开始

### 安装

**环境要求：** Python >= 3.14

```bash
# 安装 uv（如未安装）
# 参考：https://docs.astral.sh/uv/getting-started/installation/
# macOS/Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 克隆并安装依赖
git clone https://github.com/your-username/ai-release-tracker.git
cd ai-release-tracker
uv sync
```

<details>
<summary>不使用 uv</summary>

```bash
git clone https://github.com/your-username/ai-release-tracker.git
cd ai-release-tracker
pip install .
# 然后用 `python` 代替 `uv run python`
```

</details>

### 使用

```bash
# 检查所有工具的版本更新
uv run python main.py

# 单独检查 Claude Code
uv run python products/claude_code/checker.py

# 单独检查 OpenAI Codex（排除 alpha 版本）
uv run python products/codex/checker.py

# 批量推送 Claude Code 历史版本到 Telegram
uv run python products/claude_code/pusher.py              # 推送 3 个版本（默认）
uv run python products/claude_code/pusher.py --count 5    # 推送 5 个版本
uv run python products/claude_code/pusher.py --all        # 推送所有未推送版本

# 批量推送 OpenAI Codex 历史版本到 Telegram
uv run python products/codex/pusher.py

# 获取 OpenAI Codex 所有 releases 信息
uv run python products/codex/fetcher.py
```

## 配置

创建 `.env` 文件配置环境变量（脚本会自动加载）：

```bash
# Telegram 通知（每个工具独立配置，可推送到不同 bot/频道）
CLAUDE_CODE_BOT_TOKEN=your_bot_token
CLAUDE_CODE_CHAT_ID=your_chat_id
CODEX_BOT_TOKEN=your_bot_token
CODEX_CHAT_ID=your_chat_id

# AI 翻译（可选，未配置时仅发送英文）
LLM_API_KEY=your_llm_api_key
LLM_MODEL=openrouter/google/gemini-2.5-flash  # 可选，指定翻译模型
```

未配置时脚本正常运行，仅跳过对应功能。

## GitHub Actions

项目配置了自动版本检查（`.github/workflows/version-check.yml`）：

- 每 30 分钟自动运行
- 检测到新版本时自动提交版本记录更新
- 需配置 Repository Secrets：`CLAUDE_CODE_BOT_TOKEN`、`CLAUDE_CODE_CHAT_ID`、`CODEX_BOT_TOKEN`、`CODEX_CHAT_ID`、`LLM_API_KEY`

## Docker 部署

### 构建镜像

```bash
docker compose build
```

### 手动运行一次

```bash
docker compose run --rm version-checker
```

### 配置定时任务

推荐使用宿主机 cron 定时调用容器：

```bash
# 编辑 crontab
crontab -e

# 每小时检查一次
0 * * * * cd /path/to/ai-release-tracker && docker compose run --rm version-checker >> /var/log/ai-release-tracker.log 2>&1
```

docker-compose 会自动读取项目根目录的 `.env` 文件。

## 工作原理

1. 从远程获取版本信息（CHANGELOG.md 或 Atom feed）
2. 解析最新版本号和更新内容
3. 与本地 `output/*_latest_version.txt` 对比
4. 版本变化时打印更新内容并更新本地记录
5. 使用 AI 翻译更新内容（通过 LiteLLM）
6. 发送双语 Telegram 通知

## 许可证

MIT
