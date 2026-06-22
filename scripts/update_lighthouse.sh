#!/usr/bin/env bash
# =============================================================================
# update_lighthouse.sh — 灯塔每日数据一键更新（本地跑，绕开 CI 海外封锁）
#
# 流程：问财 CAN SLIM+静水 实筛 → 政策咬合 → 板块景气 → GLM灯塔信号 → 提交部署
#
# 用法：
#   export ZHIPUAI_API_KEY=xxx        # 可选，用于 GLM 灯塔信号；不设则跳过信号
#   ./scripts/update_lighthouse.sh
#
# 每日自动化（macOS launchd / cron，交易日 18:00）：
#   crontab -e
#   0 18 * * 1-5  cd /path/to/lighthouse && ZHIPUAI_API_KEY=xxx ./scripts/update_lighthouse.sh >> /tmp/lh.log 2>&1
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CANSLIM="$HOME/.claude/skills/can-slim/scripts/canslim_screener.py"
TMP="$(mktemp -d)/cand.json"
SCREEN="最近一季净利润同比增长大于30%且近3年净利润复合增长大于20%且创近120日新高"

echo "🚨 灯塔每日更新 $(date +%F)"
echo "────────────────────────────────────────"

echo "▶ 1/5  CAN SLIM+静水 选股（问财实筛）"
python3 "$CANSLIM" --screen "$SCREEN" --json > "$TMP" 2>/dev/null || { echo "❌ 问财初筛失败"; exit 1; }
python3 scraper/stocks/from_iwencai.py "$TMP"

echo "▶ 2/5  政策咬合（新闻联播板块→代表股）"
python3 scraper/stocks/policy_link.py

echo "▶ 3/5  板块景气（静水景气 × CAN SLIM 板块强度 × 政策）"
python3 scraper/stocks/sector_outlook.py

echo "▶ 4/5  灯塔信号（GLM 研判 M）"
if [ -n "${ZHIPUAI_API_KEY:-}" ]; then
  python3 scraper/llm_brief.py --signal --force || echo "⚠️ 信号生成失败，跳过"
else
  echo "⏭️  未设 ZHIPUAI_API_KEY，跳过灯塔信号"
fi

echo "▶ 5/5  提交并部署"
git add site/data/ data/analytics/ 2>/dev/null || true
if git diff --staged --quiet; then
  echo "✅ 无数据变化"
else
  git commit -m "📈 灯塔每日更新 $(date +%F)" \
    -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" >/dev/null
  git push origin main
  echo "✅ 已推送，GitHub Pages 自动部署中"
fi

echo "────────────────────────────────────────"
echo "🌐 https://ming-h.github.io/lighthouse/"
