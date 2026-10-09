#!/usr/bin/env bash
# 将本地代码同步到生产服务器并重建镜像。
#
# 目标配置读取自 .deploy.env（不入库，参考 .deploy.env.example）：
#   DEPLOY_HOST  SSH 主机（建议使用 ~/.ssh/config 中的别名）
#   DEPLOY_PATH  服务器上的项目目录
#   DEPLOY_LOCK  可选，与服务器 cron 共用的 flock 锁文件，默认 /var/lock/ai-tracker.lock
#
# 只同步代码：服务器上的 .env、output/（版本与推送状态）不会被覆盖或删除。
#
# 用法：scripts/deploy.sh [--dry-run] [--skip-tests]
set -euo pipefail

cd "$(dirname "$0")/.."

dry_run=0
skip_tests=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --skip-tests) skip_tests=1 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

if [ -f .deploy.env ]; then
  set -a
  . ./.deploy.env
  set +a
fi
: "${DEPLOY_HOST:?未设置 DEPLOY_HOST（见 .deploy.env.example）}"
: "${DEPLOY_PATH:?未设置 DEPLOY_PATH（见 .deploy.env.example）}"
DEPLOY_LOCK="${DEPLOY_LOCK:-/var/lock/ai-tracker.lock}"

if [ -n "$(git status --porcelain)" ]; then
  echo "⚠️  工作区有未提交的改动，将按当前工作区内容部署"
fi

if [ "$skip_tests" -eq 0 ]; then
  echo "==> 运行测试"
  uv run python -m unittest discover -s tests -q
fi

# rsync 按顺序匹配规则。--delete 不会删除被排除的路径，
# 因此 .env、output/ 等服务器独有内容保持原样。
rsync_args=(
  -rlptz --delete --prune-empty-dirs --itemize-changes
  --include=/.env.example
  --exclude=/.env
  --exclude='/.env.*'
  --exclude=/.deploy.env
  --exclude=/AGENTS.local.md
  --exclude=/output/
  --exclude=/.git/
  --exclude=/.venv/
  --exclude=/.review-backups/
  --exclude=/.claude/
  --exclude=__pycache__/
  --exclude='._*'
  --exclude=.DS_Store
  # 远端 rsync 持有与 cron 相同的锁，避免检查运行到一半时代码被替换
  --rsync-path="flock -w 900 $DEPLOY_LOCK rsync"
)

if [ "$dry_run" -eq 1 ]; then
  echo "==> 预演同步（不做任何修改）"
  rsync "${rsync_args[@]}" --dry-run ./ "$DEPLOY_HOST:$DEPLOY_PATH/"
  exit 0
fi

echo "==> 同步代码到 $DEPLOY_HOST:$DEPLOY_PATH"
rsync "${rsync_args[@]}" ./ "$DEPLOY_HOST:$DEPLOY_PATH/"

echo "==> 重建镜像并验证"
ssh "$DEPLOY_HOST" "flock -w 900 $DEPLOY_LOCK sh -c '
  set -e
  cd $DEPLOY_PATH
  docker compose build --quiet
  docker compose run --rm --no-deps version-checker \
    .venv/bin/python -c \"import main, products.claude_code.checker, products.codex.checker, products.openclaw.checker, products.hermes.checker\"
'"
echo "✓ 部署完成，下一次 cron 将使用新镜像"
