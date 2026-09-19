#!/bin/bash
# 매월 1일 실행 (로컬 launchd 또는 GitHub Actions) - 지난달 거래를 집계해
# Firestore monthly_reports에 저장.
set -euo pipefail

export PATH="/Users/derekchoi/.local/bin:/opt/homebrew/bin:$PATH"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -z "${GITHUB_ACTIONS:-}" ]; then
  LOG_DIR="$PROJECT_DIR/logs"
  mkdir -p "$LOG_DIR"
  TS="$(date +%Y%m%d_%H%M%S)"
  LOG_FILE="$LOG_DIR/monthly_report_${TS}.log"
  exec >> "$LOG_FILE" 2>&1
fi

echo "=== monthly report run: $(date) ==="

cd "$PROJECT_DIR"
[ -f .venv/bin/activate ] && source .venv/bin/activate

# claude CLI 헤드리스 인증용 장기 토큰 (daily_run.sh와 동일한 이유).
if [ -f "$PROJECT_DIR/secrets/claude.env" ]; then
  set -a
  source "$PROJECT_DIR/secrets/claude.env"
  set +a
fi

python src/generate_monthly_report.py

if ! python src/generate_sector_advice.py; then
  echo "!!! 자산배분 분석 생성 실패 - 월간 리포트 숫자는 이미 저장됐음"
  python src/send_telegram.py "⚠️ investment-alert: 월간 자산배분 분석(sector_allocation_advice) 생성 실패. 월간 리포트 숫자는 정상 저장됨." || true
fi

echo "=== done: $(date) ==="
