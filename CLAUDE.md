# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

版本更新监控工具集，用于检查 AI 编码工具的新版本发布。

## 运行脚本

```bash
# 运行入口文件，检查所有工具的版本更新
python main.py

# 单独检查 Claude Code 版本更新
python claude_code/claude_code_version_check.py

# 单独检查 OpenAI Codex 版本更新（排除 alpha 版本）
python codex/codex_version_check.py
```

## 依赖

```bash
pip install requests python-dotenv litellm
```

## 架构

两个独立脚本，逻辑相似：
1. 从远程获取版本信息（CHANGELOG.md 或 Atom feed）
2. 解析最新版本号和更新内容
3. 与本地 `*_latest_version.txt` 对比
4. 版本变化时打印更新内容并更新本地记录
5. 使用 AI 翻译更新内容（需配置 Gemini API Key）
6. 发送双语 Telegram 通知（英文原文 + 中文翻译）

| 脚本 | 数据源 | 版本记录文件 |
|------|--------|--------------|
| claude_code/claude_code_version_check.py | GitHub CHANGELOG.md | claude_code/claude_code_latest_version.txt |
| codex/codex_version_check.py | GitHub releases Atom feed | codex/codex_latest_version.txt |

## 项目结构

```
version-push/
├── main.py                    # 入口文件
├── notify/                    # 通知模块
│   ├── __init__.py
│   └── telegram.py            # Telegram 通知
├── translate/                 # 翻译模块
│   ├── __init__.py
│   └── gemini.py              # Gemini AI 翻译
├── claude_code/               # Claude Code 版本检查
│   ├── claude_code_version_check.py
│   └── claude_code_latest_version.txt
└── codex/                     # OpenAI Codex 版本检查
    ├── codex_version_check.py
    └── codex_latest_version.txt
```

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

使用 OpenRouter 调用 Gemini 进行更新内容翻译，通知会显示英文原文和中文翻译：

```bash
export OPENROUTER_API_KEY="your_openrouter_api_key"

# 可选：指定翻译模型，默认 openrouter/google/gemini-2.5-flash
export TRANSLATE_MODEL="openrouter/google/gemini-2.5-flash"
```

未配置时跳过翻译，仅发送英文原文。

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
0 * * * * cd /path/to/version-push && docker compose run --rm version-checker >> /var/log/version-push.log 2>&1
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
OPENROUTER_API_KEY=your_openrouter_api_key
```

docker-compose 会自动读取 `.env` 文件。
