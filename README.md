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
├─ monthly_reports     월간 집계 + AI 자산배분 의견/목표 비중/리밸런싱 제안 + 조사 기록·검증 경고 (매월 1일 자동 생성)
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
│  하단 탭바 5개: 홈 / 보유 / 일지 / 리포트 / 더보기 (거래 입력은 상단 "+ 거래" 버튼)
├─ home.html             [홈] 총평가금액, 목표 달성률·투자원금, 자산 배분 막대, 보유 상위, 최근 급등락 한 줄
├─ holdings.html         [보유] 실시간 보유현황 (Firestore 실시간 구독, 목표 비중 대비 현재 - ±5%p 초과
│                        자산군 강조, 종목 목록. 코인은 브라우저에서 직접 시세 조회)
├─ stock-detail.html     [보유] 종목 상세 (?code=로 진입 - 보유 요약, 월말 손익률 추이, 매매 이력)
├─ journal.html          [일지] 거래 일지 - 날짜별 카드 목록, 검색·필터(매수/매도/해외), 눌러서 수정/삭제.
│                        수정 시 시장=해외면 달러 단가 x 거래일 환율(frankfurter, ECB 고시)로 원화 단가/금액 재계산
├─ index.html            [리포트] 월간 리포트 (월 이동, 핵심 수치, 자산배분 막대, AI 의견 접기/펼치기 + 리밸런싱)
├─ yearly.html           [리포트] 연간 리포트 (월말 평가금액 막대, 월별 실현손익/순매수, 양도소득세 단순 추정)
├─ more.html             [더보기] 거래 입력·알림 로그·목표 바로가기, 계정/로그아웃
├─ alerts.html           [더보기] 가격 급등락 알림 로그 (날짜별, 급등/급락 필터)
├─ goal.html             [더보기] 투자 목표 (원형 진행률, 목표일까지 필요한 월 적립액, 목표 설정)
└─ add-transaction.html  매수/매도 입력 폼 (탭바 없는 전체화면, 실현손익 자동계산, 보유수량 초과 매도 경고,
                         시장=해외 선택 시 달러 단가 입력 → 실시간 환율로 원화 단가 자동계산)
```

디자인은 `style.css` 한 곳에 모은 토큰(색·글꼴)으로 관리하고, 휴대폰 설정(`prefers-color-scheme`)에
따라 라이트/다크가 자동 전환된다. 손익 색은 국내 증권 앱 관례대로 상승=빨강, 하락=파랑이고,
숫자는 Space Grotesk, 본문은 Noto Sans KR(Google Fonts)을 쓴다.

인증은 Firebase Authentication(Google 로그인)으로 하고, Firestore 보안 규칙
(`firestore.rules`)에서 허용된 계정 UID만 읽고 쓸 수 있게 제한한다.

이 앱은 SPA가 아니라 페이지(html)마다 완전히 새로 로드되는 구조라, 페이지를
이동할 때마다 Firebase가 비동기로 로그인 세션을 다시 확인하는 짧은 순간 동안
"로그인해주세요" 화면이 깜빡였었다. 각 페이지 상단에 작은 동기 스크립트를 두고
`localStorage`의 `iaAuthed` 플래그(이전에 로그인한 적이 있으면 세팅됨)를 보고
Firebase 초기화를 기다리지 않고 콘텐츠를 먼저 보여준다 - 실제로 로그아웃된
상태였다면 뒤따르는 `onAuthStateChanged`가 바로 되돌린다.

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
| `historical_prices.py` | 월간 리포트용 - 특정 날짜(월말) 기준 과거 종가 조회 (네이버/야후/업비트). 코인은 24시간 거래라 월말 KST 자정 직전 1시간봉 종가를 쓴다 (업비트 일봉은 KST 09:00 마감이라, 1일 08:00 실행 시 아직 안 끝난 봉의 그 시점 가격이 들어갔었음) |
| `refresh_live_prices.py` | 실시간 보유현황 페이지용 - 지금 이 순간 시세를 `latest_prices`에 저장, 직전 대비 ±5% 이상 변동 시 `price_alerts`에 기록 + 텔레그램 알림. 알림/시세 조회 대상은 **현재 실제로 보유 중인 종목**으로만 한정한다 (전량매도한 종목은 제외). 종목 목록은 `transactions` 전체를 스캔하지 않고 `settings/known_instruments` 캐시(종목별 `held` 여부 포함)만 읽음 (5분마다 전체 스캔하면 Firestore 무료 일일 읽기 한도 5만 건을 금방 넘김 - 실제로 겪은 사고). 이 캐시는 `add-transaction.html`/`journal.html`이 거래 내역을 조회할 때마다 `computeHoldings()` 결과로 갱신함 (`web/known-instruments.js`). 네이버/야후는 비공식 엔드포인트라 요청이 잦으면 차단/제한될 수 있음 - 실패한 종목은 조용히 건너뛰고 평단가로 대체됨 |
| `export_portfolio_snapshot.py` | 텔레그램 브리핑용 - Firestore를 `data/portfolio_snapshot.json` 형식으로 내보냄 |
| `fetch_news.py` | 보유 종목명으로 네이버 뉴스 검색 API 조회 → JSON 저장 |
| `generate_monthly_report.py` | 그 달 말 시점 과거 시세로 월간 리포트를 계산해 Firestore에 저장. "지난달"은 KST 기준으로 명시적으로 계산한다 (GitHub Actions 러너는 UTC라 `date.today()`를 그냥 쓰면 매월 1일 KST 08시 실행 시점에 UTC로는 아직 전월 말일이라 한 달 밀려 계산되는 버그가 있었음) |
| `generate_sector_advice.py` | `claude -p`로 월간 자산배분 의견을 생성해 `monthly_reports`에 덧붙임. 리밸런싱은 반기(6월/12월)에만. 자세한 동작은 아래 "월간 자산배분 의견" 참고 |
| `send_telegram.py` | 텔레그램 발송 (4096자 초과 시 자동 분할). CLI/모듈 겸용 |
| `migrate_transactions_to_firestore.py` | 1회성 - 구글시트 스냅샷을 `transactions`로 이전 (이미 완료됨) |
| `fetch_portfolio.py` | **레거시, 더 이상 안 씀** - 예전 구글시트 기반 수집 스크립트 |

## 월간 자산배분 의견 (`generate_sector_advice.py`)

매월 1일 `monthly_report_run.sh`가 월간 리포트 숫자를 만든 뒤 실행한다. 투자 판단은 코드에 넣지 않고
`claude -p`(Sonnet, WebSearch/WebFetch)가 매번 새로 조사해서 한다. 코드는 프롬프트 조립과 결과 검증·저장만 한다.

**프롬프트에 넣는 것**
- 자산군 비중, 보유 종목(수량·현재가), 지난달 의견
- **확인된 시세**: 리포트의 월말 종가(+전월 대비 등락률)를 "이미 확인된 사실"로 넘긴다. 예전엔 모델이
  시세를 웹에서 다시 찾다 실패해 "가격이 확인되지 않음"을 쓰곤 했음
- **필수 조사 체크리스트** ("무엇을 찾을지"만 정하고 판단 기준은 넣지 않음)
  - A. 매크로: 직전 FOMC(결정·투표·점도표), 미 10년물 금리, 원/달러 환율, 국제유가 (월말 기준)
  - B. 시장 월간 실측치: 금(USD/oz)·비트코인(USD) 월말 가격, 코스피·S&P500·나스닥 월간 등락률
  - C. 보유 종목별 그달 주요 뉴스 1~2개
  - D. 그 외 지정학·정책 이슈
  - 지난달 근거 중 이번 달에 뒤집힌 것은 명시적으로 점검
- **"확인 불가" 규칙**: A·B 수치만 검색어를 바꿔 2회 이상 실패했을 때 본문에 "확인 불가"로 쓴다.
  C·D에서 못 찾은 건 본문에서 뺀다 (리포트가 불확실성 목록이 되는 걸 막기 위함)

**출력 형식**
- 본문 첫 두 줄은 고정 형식 요약 (코드가 이 형식으로 누락을 검사함)
  ```
  📊 2026-10 말 | 美10년물 4.9% | 원/달러 1,334원 | 금 3,900달러 | BTC 77,400달러 | WTI 101달러
  📈 월간 | S&P500 -0.9% | 나스닥 -5.3% | 코스피 -16.2%
  ```
- 이어서 지난달 근거 점검, 자산군별 방향(늘림/줄임/유지 + 근거와 날짜). 반기 1700자, 그 외 1200자 이내
- 반기(6월/12월분)에는 목표 비중과 리밸런싱 제안 + `===REBALANCE_JSON===` 뒤에 구조화 JSON
- 마지막에 `===RESEARCH_NOTES===` 뒤로 조사 기록 (항목별 찾은 값·출처 URL, "확인 불가" 항목은 시도한 검색어)

**리밸런싱 (반기만)**
- 6월/12월분 리포트에서만 목표 비중·리밸런싱 제안을 만든다. 다른 달은 프롬프트에서 빼고, 모델이 끼워 넣어도 코드가 비운다
- 목표 비중과 현재 비중 차이가 ±5%p(`REBALANCE_BAND_PP`) 이내인 자산군은 제안하지 않는다 (프롬프트 지시 + 코드 필터)
- 국내주식/ETF는 정수 주식수로 제안 (예전엔 "100만원어치 매도"처럼 1주 단위 현실을 무시했음), 10만원 미만 소액 매매는 제안 금지

**생성 후 코드 검증**
- 첫 줄 요약에 필수 수치(美10년물·원/달러·금·BTC)가 숫자로 없으면 빠진 항목을 짚어 1회 재시도, 누락이 적은 쪽을 쓴다
- "확인 불가" 처리된 필수 수치, 생성 시각보다 뒤인 근거 날짜(예정 일정 표현은 제외)는 경고로 남긴다
- 경고는 `validation_warnings`에 저장하고 텔레그램으로 알린다

**저장 필드** (`monthly_reports/{YYYY-MM}`)

| 필드 | 내용 |
|------|------|
| `sector_allocation_advice` | 화면에 보이는 본문 |
| `target_allocation`, `rebalancing_actions` | 반기만 채워짐, 그 외 빈 값 |
| `research_notes` | 조사 기록 (화면 미표시, 검증용) |
| `validation_warnings` | 코드 검증 경고 목록 |
| `advice_generated_at` | 의견을 실제로 만든 시각. `generated_at`은 리포트 숫자 생성 시각이라 의견만 다시 만들면 어긋난다 (9월 리포트가 그랬음) |

**실행 설정**: `--tools WebSearch,WebFetch`로 웹 조사 도구만 노출 (다른 도구를 시도하다 거부되면 본문이
중복 출력됐음), 호출당 타임아웃 600초 (재시도 포함 최대 2회). 수동 실행: `python src/generate_sector_advice.py --month 2026-10`
(`--force-rebalance`로 반기가 아니어도 리밸런싱 포함)

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
