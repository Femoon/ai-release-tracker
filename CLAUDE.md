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
pip install requests
```

## 架构

两个独立脚本，逻辑相似：
1. 从远程获取版本信息（CHANGELOG.md 或 Atom feed）
2. 解析最新版本号和更新内容
3. 与本地 `*_latest_version.txt` 对比
4. 版本变化时打印更新内容并更新本地记录
5. 发现新版本时发送 Telegram 通知（需配置环境变量）

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
├── claude_code/               # Claude Code 版本检查
│   ├── claude_code_version_check.py
│   └── claude_code_latest_version.txt
└── codex/                     # OpenAI Codex 版本检查
    ├── codex_version_check.py
    └── codex_latest_version.txt
```

## Telegram 通知配置

设置以下环境变量启用 Telegram 通知：

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```

未配置时脚本正常运行，仅跳过通知功能。

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
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

docker-compose 会自动读取 `.env` 文件。
