# AI Release Tracker

A monitoring tool for tracking version updates of AI coding tools. Automatically checks for new releases and sends bilingual notifications (English + Chinese) to Telegram.

[中文文档](README_CN.md)

## Features

- Monitor multiple AI coding tools for version updates
- Parse changelogs from GitHub (CHANGELOG.md or Atom feed)
- AI-powered translation using LiteLLM (supports multiple providers)
- Bilingual Telegram notifications
- GitHub Actions for automated checking every 30 minutes
- Docker support for self-hosting

## Supported Tools

| Tool | Script | Data Source |
|------|--------|-------------|
| Claude Code | products/claude_code/checker.py | GitHub CHANGELOG.md |
| OpenAI Codex | products/codex/checker.py | GitHub releases Atom feed |

## Quick Start

### Installation

```bash
git clone https://github.com/your-username/ai-release-tracker.git
cd ai-release-tracker
pip install -r requirements.txt
```

### Usage

```bash
# Check all tools for version updates
python main.py

# Check Claude Code only
python products/claude_code/checker.py

# Check OpenAI Codex only (excludes alpha versions)
python products/codex/checker.py

# Batch push Claude Code historical versions to Telegram
python products/claude_code/pusher.py              # Push 3 versions (default)
python products/claude_code/pusher.py --count 5    # Push 5 versions
python products/claude_code/pusher.py --all        # Push all unpushed versions

# Batch push OpenAI Codex historical versions to Telegram
python products/codex/pusher.py

# Fetch all OpenAI Codex releases
python products/codex/fetcher.py
```

## Configuration

### Telegram Notifications

Each tool uses independent environment variables, allowing notifications to different bots/channels:

```bash
# Claude Code notifications
export CLAUDE_CODE_BOT_TOKEN="your_bot_token"
export CLAUDE_CODE_CHAT_ID="your_chat_id"

# OpenAI Codex notifications
export CODEX_BOT_TOKEN="your_bot_token"
export CODEX_CHAT_ID="your_chat_id"
```

Scripts run normally without configuration, just skip notifications.

### AI Translation

Uses LiteLLM for changelog translation (supports multiple providers):

```bash
export LLM_API_KEY="your_llm_api_key"

# Optional: specify translation model (default: openrouter/google/gemini-2.5-flash)
export LLM_MODEL="openrouter/google/gemini-2.5-flash"
```

Without configuration, only English content is sent.

## GitHub Actions

The project includes automated version checking (`.github/workflows/version-check.yml`):

- Runs every 30 minutes
- Automatically commits version record updates
- Required secrets: `CLAUDE_CODE_BOT_TOKEN`, `CLAUDE_CODE_CHAT_ID`, `CODEX_BOT_TOKEN`, `CODEX_CHAT_ID`, `LLM_API_KEY`

## Docker Deployment

### Build

```bash
docker compose build
```

### Run Once

```bash
docker compose run --rm version-checker
```

### Scheduled Task (Cron)

```bash
# Edit crontab
crontab -e

# Check every hour
0 * * * * cd /path/to/ai-release-tracker && docker compose run --rm version-checker >> /var/log/ai-release-tracker.log 2>&1
```

### Environment Variables

Create a `.env` file:

```bash
# Claude Code
CLAUDE_CODE_BOT_TOKEN=your_bot_token
CLAUDE_CODE_CHAT_ID=your_chat_id

# OpenAI Codex
CODEX_BOT_TOKEN=your_bot_token
CODEX_CHAT_ID=your_chat_id

# AI Translation
LLM_API_KEY=your_llm_api_key
```

## How It Works

1. Fetch version info from remote (CHANGELOG.md or Atom feed)
2. Parse latest version number and changelog content
3. Compare with local `output/*_latest_version.txt`
4. If version changed, print changelog and update local record
5. Translate content using AI (via LiteLLM)
6. Send bilingual Telegram notification

## License

MIT
