# Version Push

AI 编码工具版本更新监控工具。自动检查新版本发布，并发送双语通知（英文 + 中文）到 Telegram。

[English](README.md)

## 功能特性

- 监控多个 AI 编码工具的版本更新
- 从 GitHub 解析更新日志（CHANGELOG.md 或 Atom feed）
- 使用 LiteLLM 进行 AI 翻译（支持多种 provider）
- 双语 Telegram 通知
- GitHub Actions 每 30 分钟自动检查
- 支持 Docker 部署

## 支持的工具

| 工具 | 脚本 | 数据源 |
|------|------|--------|
| Claude Code | products/claude_code/checker.py | GitHub CHANGELOG.md |
| OpenAI Codex | products/codex/checker.py | GitHub releases Atom feed |

## 快速开始

### 安装

```bash
git clone https://github.com/your-username/version-push.git
cd version-push
pip install -r requirements.txt
```

### 使用

```bash
# 检查所有工具的版本更新
python main.py

# 单独检查 Claude Code
python products/claude_code/checker.py

# 单独检查 OpenAI Codex（排除 alpha 版本）
python products/codex/checker.py

# 批量推送 Claude Code 历史版本到 Telegram
python products/claude_code/pusher.py              # 推送 3 个版本（默认）
python products/claude_code/pusher.py --count 5    # 推送 5 个版本
python products/claude_code/pusher.py --all        # 推送所有未推送版本

# 批量推送 OpenAI Codex 历史版本到 Telegram
python products/codex/pusher.py

# 获取 OpenAI Codex 所有 releases 信息
python products/codex/fetcher.py
```

## 配置

### Telegram 通知

每个工具使用独立的环境变量，可推送到不同的 bot 和频道：

```bash
# Claude Code 通知配置
export CLAUDE_CODE_BOT_TOKEN="your_bot_token"
export CLAUDE_CODE_CHAT_ID="your_chat_id"

# OpenAI Codex 通知配置
export CODEX_BOT_TOKEN="your_bot_token"
export CODEX_CHAT_ID="your_chat_id"
```

未配置时脚本正常运行，仅跳过通知功能。

### AI 翻译

使用 LiteLLM 进行更新内容翻译（支持多种 provider）：

```bash
export LLM_API_KEY="your_llm_api_key"

# 可选：指定翻译模型，默认 openrouter/google/gemini-2.5-flash
export LLM_MODEL="openrouter/google/gemini-2.5-flash"
```

未配置时跳过翻译，仅发送英文原文。

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
0 * * * * cd /path/to/version-push && docker compose run --rm version-checker >> /var/log/version-push.log 2>&1
```

### 环境变量配置

创建 `.env` 文件：

```bash
# Claude Code
CLAUDE_CODE_BOT_TOKEN=your_bot_token
CLAUDE_CODE_CHAT_ID=your_chat_id

# OpenAI Codex
CODEX_BOT_TOKEN=your_bot_token
CODEX_CHAT_ID=your_chat_id

# AI 翻译
LLM_API_KEY=your_llm_api_key
```

docker-compose 会自动读取 `.env` 文件。

## 工作原理

1. 从远程获取版本信息（CHANGELOG.md 或 Atom feed）
2. 解析最新版本号和更新内容
3. 与本地 `output/*_latest_version.txt` 对比
4. 版本变化时打印更新内容并更新本地记录
5. 使用 AI 翻译更新内容（通过 LiteLLM）
6. 发送双语 Telegram 通知

## 许可证

MIT
