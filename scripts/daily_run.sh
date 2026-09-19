#!/bin/bash
# 매일 아침 실행되는 스크립트 (로컬 launchd 또는 GitHub Actions 둘 다에서 재사용).
# 1) Firestore(거래 내역) + 실시간 시세 + 네이버 뉴스로 최신 스냅샷 갱신 (결정적 스크립트)
# 2) claude -p로 스냅샷을 분석 + 추천 메시지 작성 (WebSearch만 허용된 순수 텍스트 생성 — 로컬 파일/Bash 접근 없음)
# 3) 결과를 텔레그램으로 발송
set -euo pipefail

# launchd는 PATH를 /usr/bin:/bin:/usr/sbin:/sbin 로만 채워서 실행하므로,
# claude CLI(~/.local/bin)와 homebrew 도구들을 못 찾는다. 명시적으로 추가한다.
# (GitHub Actions에선 존재하지 않는 경로라 그냥 무시됨)
export PATH="/Users/derekchoi/.local/bin:/opt/homebrew/bin:$PATH"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# GitHub Actions에서는 자체 로그 UI가 있으니 파일로 리다이렉트하지 않는다.
if [ -z "${GITHUB_ACTIONS:-}" ]; then
  LOG_DIR="$PROJECT_DIR/logs"
  mkdir -p "$LOG_DIR"
  TS="$(date +%Y%m%d_%H%M%S)"
  LOG_FILE="$LOG_DIR/${TS}.log"
  exec >> "$LOG_FILE" 2>&1
fi

echo "=== investment-alert daily run: $(date) ==="

cd "$PROJECT_DIR"
[ -f .venv/bin/activate ] && source .venv/bin/activate

# claude CLI 헤드리스(비대화형) 인증용 장기 토큰. 로컬에선 secrets/claude.env 파일에서
# 읽고, GitHub Actions에선 워크플로우가 CLAUDE_CODE_OAUTH_TOKEN을 이미 환경변수로 넣어주므로
# 파일이 없으면 건너뛴다. (로그인 키체인 세션에 의존하면 무인 실행 환경에서 인증에
# 접근하지 못해 "Not logged in"으로 조용히 실패한다.)
if [ -f "$PROJECT_DIR/secrets/claude.env" ]; then
  set -a
  source "$PROJECT_DIR/secrets/claude.env"
  set +a
fi

echo "--- 1. 포트폴리오/뉴스 스냅샷 갱신 ---"
python src/refresh_live_prices.py
python src/export_portfolio_snapshot.py
python src/fetch_news.py

PORTFOLIO_JSON="$(cat data/portfolio_snapshot.json)"
NEWS_JSON="$(cat data/news_snapshot.json)"

PROMPT="$(cat <<PROMPT_EOF
너는 개인 투자자를 위한 아침 브리핑을 작성하는 애널리스트다. 아래 데이터를 바탕으로 텔레그램 메시지 본문을 작성하라.

## 입력 데이터

### 보유 현황 + 거래 내역 (portfolio_snapshot.json)
$PORTFOLIO_JSON

### 보유 종목별 최신 뉴스 (news_snapshot.json, 종목명 -> 기사 리스트)
$NEWS_JSON

## 작성 지침

1. **투자 패턴/특징 반영**: transactions(거래 내역)를 보고 이 투자자의 패턴(매수 빈도, 섹터/자산군 쏠림, DCA vs 몰빵 성향, 코인/ETF/개별주 비중 등)을 감안해서 조언 톤을 맞춰라. 패턴 자체를 매번 길게 설명하지 말고, 조언에 자연스럽게 녹여라.
2. **보유 종목 코멘트**: holdings 각각에 대해 뉴스와 현재 수익률(profit_pct)을 참고해 "계속 보유/비중 축소 고려/추가 매수 고려/주의 필요" 같은 방향성을 1줄씩 제시하라. 관련 뉴스가 없으면 억지로 만들지 말고 수익률 기준으로만 코멘트하라. 확정적 지시가 아니라 참고 의견 톤으로 작성하라 (투자 책임은 본인에게 있음을 암시).
3. **구체적 가격 제안 (WebSearch로 확인된 경우만)**: "추가 매수 고려"나 "비중 축소 고려" 방향을 제시하는 종목에 한해, WebSearch로 해당 종목/자산의 애널리스트 목표가, 52주 최고·최저가, 최근 지지선/저항선 등 신뢰 가능한 근거를 실제로 찾을 수 있으면 "OOO원대에서 분할 매수 고려", "OOO원 부근이 저항선" 처럼 구체적 가격·구간과 그 근거(예: "52주 저점 기준", "증권사 목표가 기준")를 함께 제시하라. **WebSearch로 확인 못 한 종목에는 절대 숫자를 지어내지 말고 방향성 코멘트만 유지하라.** 목표가 개념이 없는 자산(코인, 국내 ETF 등)은 최근 가격대/변동성 설명으로 대체하라.
4. **신규 관심 정보**: 보유 종목에 없는 새로운 투자 아이디어나 눈여겨볼 섹터/테마를 1~3개 제안하라. 필요하면 WebSearch로 오늘 기준 최신 시장 동향을 확인해서 반영하라. 추측이나 오래된 지식으로 "최신"이라고 단정하지 말고, 확인이 안 되면 트렌드 수준으로만 언급하라.
5. **형식**: 텔레그램 발송용 순수 텍스트(HTML/마크다운 태그 금지, 이모지와 줄바꿈만 사용). 총 길이는 공백 포함 1500자 이내로 간결하게. 섹션 구분은 이모지+굵은 느낌의 제목 줄(예: "📊 오늘의 포트폴리오") 정도로만.
6. 마지막 줄에 "※ 투자 판단은 참고용이며 최종 책임은 본인에게 있습니다." 를 반드시 포함하라.
7. **출력은 텔레그램 메시지 본문 그 자체만** 출력하라. 서두 설명("알겠습니다" 등)이나 후기 없이, 메시지 본문만 그대로 출력해야 한다.
PROMPT_EOF
)"

echo "--- 2. Claude 분석 + 메시지 작성 ---"
set +e
CLAUDE_ERR_FILE="$(mktemp)"
CLAUDE_OUT_FILE="$(mktemp)"

# macOS 기본 bash에는 GNU timeout이 없다. claude 인증 토큰이 만료되면
# 헤드리스 환경(launchd, TTY 없음)에서 로그인 프롬프트를 띄운 채 영원히
# 멈춰버리는 사고가 실제로 있었으므로(토큰 만료를 33일간 못 알아챔),
# 백그라운드 실행 + 워치독으로 강제 타임아웃을 구현한다.
CLAUDE_TIMEOUT=300
claude -p "$PROMPT" --model claude-sonnet-5 --allowedTools "WebSearch" --output-format text >"$CLAUDE_OUT_FILE" 2>"$CLAUDE_ERR_FILE" &
CLAUDE_PID=$!

WAITED=0
while kill -0 "$CLAUDE_PID" 2>/dev/null; do
  sleep 5
  WAITED=$((WAITED + 5))
  if [ "$WAITED" -ge "$CLAUDE_TIMEOUT" ]; then
    echo "!!! claude -p가 ${CLAUDE_TIMEOUT}초 내 응답 없음 (인증 토큰 만료 가능성) — 강제 종료"
    kill -9 "$CLAUDE_PID" 2>/dev/null
    break
  fi
done
wait "$CLAUDE_PID" 2>/dev/null
CLAUDE_EXIT=$?
MESSAGE="$(cat "$CLAUDE_OUT_FILE")"
set -e

if [ $CLAUDE_EXIT -ne 0 ] || [ -z "$MESSAGE" ]; then
  echo "!!! 메시지 생성 실패 (exit=$CLAUDE_EXIT) — 발송 중단"
  echo "--- claude stderr ---"
  cat "$CLAUDE_ERR_FILE"
  rm -f "$CLAUDE_ERR_FILE" "$CLAUDE_OUT_FILE"
  python src/send_telegram.py "⚠️ investment-alert: 오늘 아침 브리핑 생성 실패 (exit=$CLAUDE_EXIT). claude 인증 토큰이 만료됐을 수 있으니 claude setup-token으로 재발급 필요." || true
  exit 1
fi
rm -f "$CLAUDE_ERR_FILE" "$CLAUDE_OUT_FILE"

echo "--- 3. 텔레그램 발송 ---"
python src/send_telegram.py "$MESSAGE"

echo "=== done: $(date) ==="
