# investment-alert

개인 투자 포트폴리오(구글 시트 기반)를 매일 아침 요약해 텔레그램으로 보내주는 개인용 서비스.

이 저장소는 **결정적(deterministic) 데이터 파이프라인**만 담는다.
"보유 종목 조언 / 신규 투자 정보" 같은 **투자 판단 로직은 여기에 하드코딩되어 있지 않다.**
매일 아침 스케줄된 Claude Code 세션이 아래 스냅샷 파일(`data/*.json`)을 읽고
직접 판단해 메시지를 작성한 뒤 `send_telegram.py`로 발송한다.

## 실행 순서

```
1) python src/fetch_portfolio.py   # 구글 시트 -> data/portfolio_snapshot.json
2) python src/fetch_news.py        # 보유 종목별 뉴스 -> data/news_snapshot.json
3) (스케줄된 Claude 세션이 위 두 JSON을 읽고 분석 + 메시지 작성)
4) python src/send_telegram.py "<작성된 메시지>"   # 텔레그램 발송
```

## 스크립트 역할

| 파일 | 역할 |
|------|------|
| `src/config.py` | `secrets/`의 자격증명(.env, 서비스 계정 키)과 경로 상수 로드 |
| `src/fetch_portfolio.py` | 구글 시트 두 탭(거래 로그 `📊주식내역`, 보유 현황 `📈주식현황상세`)을 정제된 JSON으로 저장 |
| `src/fetch_news.py` | `holdings` 종목명으로 네이버 뉴스 검색 API 조회 → JSON 저장 |
| `src/send_telegram.py` | 텔레그램 발송 (4096자 초과 시 자동 분할). CLI/모듈 겸용 |

## 사전 준비

- `.venv/` (python 3.13) — 실행 전 `source .venv/bin/activate`
- `secrets/google-service-account.json` — Google Sheets 서비스 계정 키 (시트에 뷰어 공유됨)
- `secrets/naver-api.env` — `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`
- `secrets/telegram.env` — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

> `secrets/`와 `data/`는 `.gitignore`로 제외된다. 커밋하지 말 것.

## 산출물 (`data/`)

- `portfolio_snapshot.json` — `{ fetched_at, transactions[], holdings[] }`
- `news_snapshot.json` — `{ "종목명": [ {title, link, description, pub_date}, ... ] }`
