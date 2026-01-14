# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

版本更新监控工具集，用于检查 AI 编码工具的新版本发布。

## 运行脚本

```bash
# 运行入口文件，检查所有工具的版本更新
uv run python main.py

# 单独检查 Claude Code 版本更新
uv run python products/claude_code/checker.py

# 单独检查 OpenAI Codex 版本更新（排除 alpha 版本）
uv run python products/codex/checker.py

# 批量推送 Claude Code 历史版本到 Telegram（默认推送 3 个）
uv run python products/claude_code/pusher.py
uv run python products/claude_code/pusher.py --count 5  # 推送 5 个
uv run python products/claude_code/pusher.py --all       # 推送所有未推送版本

# 批量推送 OpenAI Codex 历史版本到 Telegram
uv run python products/codex/pusher.py

# 获取 OpenAI Codex 所有 releases 信息
uv run python products/codex/fetcher.py
```

## 依赖

**环境要求：** Python >= 3.14

```bash
# 安装 uv（如未安装）
# 参考：https://docs.astral.sh/uv/getting-started/installation/
# macOS/Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 安装项目依赖
uv sync
```

不使用 uv 时：`pip install .`，然后用 `python` 代替 `uv run python`。

## 架构

版本检查脚本逻辑：
1. 从远程获取版本信息（CHANGELOG.md 或 Atom feed）
2. 解析最新版本号和更新内容
3. 与本地 `output/*_latest_version.txt` 对比
4. 版本变化时打印更新内容并更新本地记录
5. 使用 AI 翻译更新内容（通过 LiteLLM 调用 LLM API）
6. 发送双语 Telegram 通知（英文原文 + 中文翻译）

| 脚本 | 数据源 | 版本记录文件 |
|------|--------|--------------|
| products/claude_code/checker.py | GitHub CHANGELOG.md | output/claude_code_latest_version.txt |
| products/codex/checker.py | GitHub releases Atom feed | output/codex_latest_version.txt |

历史推送脚本 `products/claude_code/pusher.py` 会记录已推送版本到 `output/claude_code_pushed_versions.txt`，避免重复推送。

## GitHub Actions

项目配置了自动版本检查（`.github/workflows/version-check.yml`）：
- 每 30 分钟自动运行
- 检测到新版本时自动提交版本记录更新
- 需配置 Repository Secrets: `CLAUDE_CODE_BOT_TOKEN`, `CLAUDE_CODE_CHAT_ID`, `CODEX_BOT_TOKEN`, `CODEX_CHAT_ID`, `LLM_API_KEY`

## Telegram 通知配置

每个工具使用独立的环境变量，可推送到不同的 bot 和频道：

```bash
# Claude Code 通知配置
export CLAUDE_CODE_BOT_TOKEN="your_claude_code_bot_token"
export CLAUDE_CODE_CHAT_ID="your_claude_code_chat_id"

# OpenAI Codex 通知配置
export CODEX_BOT_TOKEN="your_codex_bot_token"
export CODEX_CHAT_ID="your_codex_chat_id"
```

未配置时脚本正常运行，仅跳过通知功能。

## AI 翻译配置

使用 LiteLLM 调用 LLM API 进行更新内容翻译，通知会显示英文原文和中文翻译：

```bash
export LLM_API_KEY="your_llm_api_key"

# 可选：指定翻译模型，默认 openrouter/google/gemini-2.5-flash
export LLM_MODEL="openrouter/google/gemini-2.5-flash"
```

未配置时跳过翻译，仅发送英文原文。

## Telegraph 长文发布配置（可选）

当更新日志内容超过 Telegram 消息长度限制（4096字符）时，系统会自动将内容发布到 Telegraph，并在 Telegram 发送文章链接。

```bash
# Telegraph 配置（必需，用于发布长文）
export TELEGRAPH_ACCESS_TOKEN="your_telegraph_token"

# 可选：自定义文章署名
export TELEGRAPH_AUTHOR_NAME="AI Release Tracker"
export TELEGRAPH_AUTHOR_URL="https://t.me/your_channel"
```

未配置时跳过 Telegraph 发布，超长消息将发送失败。

## GitHub API 配置（可选）

用于 codex checker 和 fetcher 访问 GitHub API，避免速率限制：

```bash
export GH_TOKEN="your_github_token"
```

**注意**：不要使用 `GITHUB_TOKEN`，这是 GitHub Actions 的保留变量名。

未配置时脚本仍可运行，但可能遇到速率限制（60 次/小时）。配置后提升至 5000 次/小时。

Token 获取方式：GitHub Settings → Developer settings → Personal access tokens → 创建 token（无需特殊权限，public_repo 访问即可）。

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

推荐使用宿主机 cron 定时调用容器（资源消耗最低）：

```bash
# 编辑 crontab
crontab -e

# 每小时检查一次
0 * * * * cd /path/to/ai-release-tracker && docker compose run --rm version-checker >> /var/log/ai-release-tracker.log 2>&1
```

### 配置 Telegram 通知

创建 `.env` 文件：

```bash
# Claude Code 通知配置
CLAUDE_CODE_BOT_TOKEN=your_claude_code_bot_token
CLAUDE_CODE_CHAT_ID=your_claude_code_chat_id

# OpenAI Codex 通知配置
CODEX_BOT_TOKEN=your_codex_bot_token
CODEX_CHAT_ID=your_codex_chat_id

# AI 翻译配置
LLM_API_KEY=your_llm_api_key

# GitHub API 配置（可选，避免 API 速率限制）
# 注意：不要使用 GITHUB_TOKEN（GitHub Actions 保留变量）
# GH_TOKEN=your_github_token
```

docker-compose 会自动读取 `.env` 文件。
