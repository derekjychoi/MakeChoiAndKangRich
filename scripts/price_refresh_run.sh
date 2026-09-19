#!/bin/bash
# 5분 간격으로 launchd가 호출 - transactions 컬렉션의 모든 종목 실시간 시세를
# latest_prices에 갱신한다. 로그가 많이 쌓이므로 롤링 로그 파일 하나만 씀.
set -euo pipefail

export PATH="/Users/derekchoi/.local/bin:/opt/homebrew/bin:$PATH"

PROJECT_DIR="/Users/derekchoi/investment-alert"
LOG_FILE="$PROJECT_DIR/logs/price_refresh.log"

cd "$PROJECT_DIR"
source .venv/bin/activate

{
  echo "=== price refresh: $(date) ==="
  python src/refresh_live_prices.py
} >> "$LOG_FILE" 2>&1

# 로그 파일이 너무 커지지 않도록 마지막 2000줄만 유지
tail -n 2000 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
