# investment-alert

개인 투자 포트폴리오를 관리하는 개인용 서비스. 두 부분으로 구성된다.

1. **매일 아침 텔레그램 브리핑**: 로컬 Mac(launchd)이 매일 08:00에 자동으로 보유현황을
   갱신하고, 스케줄된 Claude Code 세션이 분석 메시지를 작성해 텔레그램으로 발송한다.
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
├─ latest_prices       실시간(근사) 시세 캐시 (5분마다 launchd가 갱신)
└─ monthly_reports     월간 집계 + AI 자산배분 의견 (매월 1일 자동 생성)

로컬 Mac (launchd, 무인 실행)
├─ daily_run.sh              매일 08:00 - 텔레그램 브리핑
├─ price_refresh_run.sh      5분마다 - latest_prices 갱신 (실시간 보유현황 페이지용)
└─ monthly_report_run.sh     매월 1일 08:10 - 지난달 리포트 + AI 자산배분 의견

web/ (GitHub Pages, gh-pages 브랜치)
├─ index.html            월간 리포트 (월 선택/페이징, 자산배분 파이차트, AI 의견 + 리밸런싱 표)
├─ yearly.html           연간 리포트 (월별 순매수/실현손익/평가금액 추이)
├─ holdings.html         실시간 보유현황 (Firestore 실시간 구독, 코인은 브라우저에서 직접 시세 조회)
├─ journal.html          전체 거래 일지 (검색/수정/삭제)
└─ add-transaction.html  매수/매도 입력 폼
```

인증은 Firebase Authentication(Google 로그인)으로 하고, Firestore 보안 규칙
(`firestore.rules`)에서 허용된 계정 UID만 읽고 쓸 수 있게 제한한다.

## launchd 자동 실행 스크립트

| 스크립트 | 주기 | 역할 |
|------|------|------|
| `scripts/daily_run.sh` | 매일 08:00 | 시세 갱신 → 스냅샷/뉴스 갱신 → `claude -p` 분석 → 텔레그램 발송 |
| `scripts/price_refresh_run.sh` | 5분마다 | 보유 종목 실시간(근사) 시세를 `latest_prices`에 갱신 |
| `scripts/monthly_report_run.sh` | 매월 1일 08:10 | 지난달 리포트 생성 + AI 자산배분 의견/리밸런싱 제안 생성 |

## 핵심 스크립트 (`src/`)

| 파일 | 역할 |
|------|------|
| `config.py` | `secrets/`의 자격증명과 경로 상수 로드 |
| `firestore_client.py` | Firestore Admin SDK 클라이언트 (프로세스당 1회 초기화) |
| `asset_classify.py` | 종목을 자산군(개별주식/ETF/금/코인)·시세 소스로 분류하는 결정적 규칙 |
| `holdings_calc.py` | 거래 내역 → 보유 종목(평균단가법)을 계산 |
| `historical_prices.py` | 월간 리포트용 - 특정 날짜(월말) 기준 과거 종가 조회 (네이버/야후/업비트) |
| `refresh_live_prices.py` | 실시간 보유현황 페이지용 - 지금 이 순간 시세를 `latest_prices`에 저장 |
| `export_portfolio_snapshot.py` | 텔레그램 브리핑용 - Firestore를 `data/portfolio_snapshot.json` 형식으로 내보냄 |
| `fetch_news.py` | 보유 종목명으로 네이버 뉴스 검색 API 조회 → JSON 저장 |
| `generate_monthly_report.py` | 그 달 말 시점 과거 시세로 월간 리포트를 계산해 Firestore에 저장 |
| `generate_sector_advice.py` | `claude -p`로 자산배분 의견 + 구조화된 리밸런싱 제안(JSON)을 생성 |
| `send_telegram.py` | 텔레그램 발송 (4096자 초과 시 자동 분할). CLI/모듈 겸용 |
| `migrate_transactions_to_firestore.py` | 1회성 - 구글시트 스냅샷을 `transactions`로 이전 (이미 완료됨) |
| `fetch_portfolio.py` | **레거시, 더 이상 안 씀** - 예전 구글시트 기반 수집 스크립트 |

## 사전 준비 (`secrets/`, `.gitignore`로 제외됨)

- `.venv/` (python 3.13) — 실행 전 `source .venv/bin/activate`
- `claude.env` — `claude setup-token`으로 발급한 헤드리스 인증용 장기 토큰
- `firebase-service-account.json` — Firestore Admin SDK 서비스 계정 키
- `naver-api.env` — `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` (뉴스 검색용)
- `telegram.env` — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `google-service-account.json` — 레거시, 현재 미사용

## 웹앱 배포

- Firebase 프로젝트: Firestore + Authentication(Google 로그인만 허용된 UID로 제한)
- `web/` 폴더를 `gh-pages` 브랜치로 배포: `git subtree push --prefix web origin gh-pages`
- `web/firebase-config.js`는 공개돼도 되는 클라이언트 설정값 (Firestore 규칙이 실제 접근 제어를 담당)
- Firebase Authentication 승인된 도메인에 GitHub Pages 도메인을 추가해야 로그인이 동작한다
