# investment-alert

개인 투자 포트폴리오를 관리하는 개인용 서비스. 두 부분으로 구성된다.

1. **매일 아침 텔레그램 브리핑**: 외부 크론(cron-job.org)이 GitHub Actions를 깨워
   매일 08:00 KST 근처에 자동으로 보유현황을 갱신하고, 스케줄된 Claude Code 세션이
   분석 메시지를 작성해 텔레그램으로 발송한다.
2. **웹 리포트 앱** (`web/`, GitHub Pages로 배포): 거래 입력, 전체 거래 일지, 실시간 보유현황,
   월간/연간 리포트를 Google 로그인 후 볼 수 있는 정적 웹앱.

Firestore가 거래 내역(`transactions`)의 **유일한 원본**이다. 예전에는 구글시트를 수기로
관리했지만 지금은 웹 입력 폼에서 직접 기록한다.

이 저장소는 **결정적(deterministic) 데이터 파이프라인**만 담는다.
"보유 종목 조언 / 자산배분 방향" 같은 **투자 판단 로직은 하드코딩되어 있지 않다.**
매일/매달 새로 스케줄된 Claude Code 세션이 WebSearch로 직접 최신 정보를 찾아 판단한다.

## 아키텍처

```
Firestore (makechoiandkangrich 프로젝트)
├─ transactions        거래 내역 (원본, 웹 입력 폼이 직접 씀)
├─ latest_prices       실시간(근사) 시세 캐시 (외부 크론이 5분마다 GitHub Actions를 깨워 갱신)
├─ monthly_reports     월간 집계 + AI 자산배분 의견(target_allocation)/리밸런싱 제안 (매월 1일 자동 생성)
├─ price_alerts        가격 급등락 알림 기록 (refresh_live_prices.py가 씀, alerts.html에서 조회)
└─ settings            투자 목표(investment_goal), 종목 목록 캐시(known_instruments) - 클라이언트가 직접 읽고 씀

cron-job.org (외부, 무료) --workflow_dispatch API 호출--> GitHub Actions
├─ daily-briefing.yml    매일 08:00 KST 근처 - 텔레그램 브리핑
├─ price-refresh.yml     5분마다 - latest_prices 갱신 + 직전 대비 ±5% 급등락 텔레그램 알림
└─ monthly-report.yml    매월 1일 아침 - 지난달 리포트 + AI 자산배분 의견

GitHub Actions 자체의 `schedule` 트리거는 안 쓴다 - 이 저장소에서 몇 시간씩
밀리는 걸 실측으로 확인함 (15분 간격으로 72분 동안 5번 뜰 기회가 있었는데
0번 뜸). workflow_dispatch(API/버튼으로 즉시 실행)는 지연 없이 바로 도는 걸
확인해서, 외부 크론이 정해진 시각마다 그 API를 대신 호출해주는 방식으로
바꿨다.

web/ (GitHub Pages, gh-pages 브랜치, PWA로 홈 화면 추가 가능)
├─ home.html             홈 대시보드 (총평가금액, 목표 진행률, 자산배분, 최근 알림, 바로가기)
├─ index.html            월간 리포트 (월 선택/페이징, 자산배분 파이차트, AI 의견 + 리밸런싱 표)
├─ yearly.html           연간 리포트 (월별 순매수/실현손익/평가금액 추이, 양도소득세 단순 추정)
├─ holdings.html         실시간 보유현황 (Firestore 실시간 구독, 목표비중 대비 현재 비교,
│                        코인은 브라우저에서 직접 시세 조회)
├─ journal.html          전체 거래 일지 (검색/수정/삭제)
├─ add-transaction.html  매수/매도 입력 폼 (실현손익 자동계산, 보유수량 초과 매도 경고)
├─ stock-detail.html     종목 상세 (?code=로 진입 - 매매 이력 + 월별 손익률 추이)
├─ alerts.html           가격 급등락 알림 로그 (price_alerts 컬렉션)
└─ goal.html             투자 목표 설정 + 진행률 미터
```

인증은 Firebase Authentication(Google 로그인)으로 하고, Firestore 보안 규칙
(`firestore.rules`)에서 허용된 계정 UID만 읽고 쓸 수 있게 제한한다.

## 자동 실행 (cron-job.org → GitHub Actions workflow_dispatch)

| 워크플로우 | 주기(외부 크론 기준) | 실제 실행 스크립트 | 필요한 저장소 시크릿 |
|------|------|------|------|
| `daily-briefing.yml` | 매일 08:00 KST 근처 | `scripts/daily_run.sh` | `CLAUDE_CODE_OAUTH_TOKEN`, `FIREBASE_SERVICE_ACCOUNT_JSON`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `price-refresh.yml` | 5분마다 | `python src/refresh_live_prices.py` | `FIREBASE_SERVICE_ACCOUNT_JSON`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `monthly-report.yml` | 매월 1일 아침 | `scripts/monthly_report_run.sh` | `CLAUDE_CODE_OAUTH_TOKEN`, `FIREBASE_SERVICE_ACCOUNT_JSON`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |

세 워크플로우 모두 `on: workflow_dispatch` 하나만 트리거로 갖고 있다. cron-job.org에
등록된 크론잡이 정해진 시각마다 아래 형태로 GitHub API를 호출해서 깨운다:

```
POST https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow-file}/dispatches
Authorization: Bearer <이 저장소 전용, Actions:Read-and-write 권한만 있는 fine-grained PAT>
Accept: application/vnd.github+json
Content-Type: application/json

{"ref": "main"}
```

PAT는 cron-job.org의 비공개 설정에만 저장되고, 저장소나 웹페이지 JS에는 들어가지
않는다 (권한도 이 저장소의 Actions 읽기/쓰기로만 좁혀둠).

스크립트는 로컬 launchd에서도 그대로 재사용 가능하도록 짜여 있다 (`scripts/*.sh`가 실행
위치를 스스로 계산하고, `.venv`/`secrets/*.env` 파일은 있을 때만 사용). 다만 지금은
GitHub Actions로만 돌리고 있고, 로컬 launchd 등록은 전부 해제된 상태다.

Claude Code CLI는 워크플로우 안에서 공식 설치 스크립트(`curl -fsSL https://claude.ai/install.sh | bash`)로
매번 새로 설치한다.

## 핵심 스크립트 (`src/`)

| 파일 | 역할 |
|------|------|
| `config.py` | `secrets/`의 자격증명과 경로 상수 로드 |
| `firestore_client.py` | Firestore Admin SDK 클라이언트 (프로세스당 1회 초기화) |
| `asset_classify.py` | 종목을 자산군(개별주식/ETF/금/코인)·시세 소스로 분류하는 결정적 규칙 |
| `holdings_calc.py` | 거래 내역 → 보유 종목(평균단가법)을 계산 |
| `historical_prices.py` | 월간 리포트용 - 특정 날짜(월말) 기준 과거 종가 조회 (네이버/야후/업비트) |
| `refresh_live_prices.py` | 실시간 보유현황 페이지용 - 지금 이 순간 시세를 `latest_prices`에 저장, 직전 대비 ±5% 이상 변동 시 `price_alerts`에 기록 + 텔레그램 알림. 종목 목록은 `transactions` 전체를 스캔하지 않고 `settings/known_instruments` 캐시만 읽음 (5분마다 전체 스캔하면 Firestore 무료 일일 읽기 한도 5만 건을 금방 넘김 - 실제로 겪은 사고). 이 캐시는 `add-transaction.html`이 저장할 때마다 갱신함. 네이버/야후는 비공식 엔드포인트라 요청이 잦으면 차단/제한될 수 있음 - 실패한 종목은 조용히 건너뛰고 평단가로 대체됨 |
| `export_portfolio_snapshot.py` | 텔레그램 브리핑용 - Firestore를 `data/portfolio_snapshot.json` 형식으로 내보냄 |
| `fetch_news.py` | 보유 종목명으로 네이버 뉴스 검색 API 조회 → JSON 저장 |
| `generate_monthly_report.py` | 그 달 말 시점 과거 시세로 월간 리포트를 계산해 Firestore에 저장 |
| `generate_sector_advice.py` | `claude -p`로 자산배분 의견 + 구조화된 목표비중(`target_allocation`)·리밸런싱 제안(JSON)을 생성 |
| `send_telegram.py` | 텔레그램 발송 (4096자 초과 시 자동 분할). CLI/모듈 겸용 |
| `migrate_transactions_to_firestore.py` | 1회성 - 구글시트 스냅샷을 `transactions`로 이전 (이미 완료됨) |
| `fetch_portfolio.py` | **레거시, 더 이상 안 씀** - 예전 구글시트 기반 수집 스크립트 |

## 사전 준비

로컬에서 수동으로 스크립트를 돌릴 땐 `secrets/`(`.gitignore`로 제외됨) 파일 필요:

- `.venv/` (python 3.13) — 실행 전 `source .venv/bin/activate`
- `claude.env` — `claude setup-token`으로 발급한 헤드리스 인증용 장기 토큰
- `firebase-service-account.json` — Firestore Admin SDK 서비스 계정 키
- `naver-api.env` — `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` (뉴스 검색용)
- `telegram.env` — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `google-service-account.json` — 레거시, 현재 미사용

GitHub Actions에서 돌릴 땐 위 값들을 저장소 시크릿(Settings → Secrets and variables →
Actions)으로 등록한다. 값을 확인할 땐 `cat secrets/xxx.env` 등을 Claude Code 세션이 아닌
**별도 터미널**에서 실행할 것 (`!` 명령은 결과가 대화 기록에 남는다). `firebase-service-account.json`처럼
민감도가 높은 키가 실수로 노출되면 재발급 + 기존 키 폐기를 권장한다.

## 웹앱 배포

- Firebase 프로젝트: Firestore + Authentication(Google 로그인만 허용된 UID로 제한)
- `web/` 폴더를 `gh-pages` 브랜치로 배포: `git subtree push --prefix web origin gh-pages`
- `web/firebase-config.js`는 공개돼도 되는 클라이언트 설정값 (Firestore 규칙이 실제 접근 제어를 담당)
- Firebase Authentication 승인된 도메인에 GitHub Pages 도메인을 추가해야 로그인이 동작한다
