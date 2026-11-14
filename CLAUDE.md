# CLAUDE.md

이 저장소에서 작업하는 Claude Code 세션용 안내. 프로젝트 구조/아키텍처/스크립트 설명은
README에 있고 아래에서 그대로 불러온다. 이 파일엔 README에 없는 **작업 규칙과 결정 배경**만 적는다.

@README.md

## 대화 / 작업 방식

- 사용자와는 한국어로 대화한다.
- 커밋과 배포는 사용자가 요청할 때만 한다 ("커밋해줘", "배포해줘"). 작업이 끝나면 변경 요약과
  검증 범위(무엇을 실제로 확인했고 무엇은 못 했는지)를 알려주고 커밋 여부를 묻는다.
- 기능을 바꾸면 README의 해당 설명(아키텍처 트리, 핵심 스크립트 표)도 같이 고친다.
- 커밋할 때, 이번 작업에서 새로 정한 정책·규칙이나 결정 배경이 있으면 이 `CLAUDE.md`도 같이
  고쳐서 같은 커밋에 포함한다 (예: "리밸런싱 ±5%p"). 단순 버그 수정처럼 새 규칙이 없으면 고치지
  않는다 - 파일이 길어지면 중요한 규칙이 묻힌다.
- 커밋 메시지는 한국어로: 첫 줄에 무엇을 했는지, 본문에 **왜** 그렇게 했는지(사용자 피드백,
  실제로 겪은 버그/사고 등)를 적는다. `git log`의 기존 커밋들이 참고 예시.

## 배포

| 바뀐 곳 | 배포 방법 |
|------|------|
| `web/` | `git push origin main` 후 `git subtree push --prefix web origin gh-pages` (GitHub Pages, 반영까지 1~2분) |
| `src/`, `scripts/`, `.github/` | `git push origin main`만 하면 됨 - 워크플로우가 실행 시 main을 checkout |

- 웹 배포 후 확인: `curl -s https://derekjychoi.github.io/MakeChoiAndKangRich/<페이지>.html`로
  변경 내용이 들어갔는지 grep. 사이트 열기: `open https://derekjychoi.github.io/MakeChoiAndKangRich/`
- 서비스워커(`web/sw.js`)는 캐싱 없이 네트워크 통과만 하므로 새로고침하면 바로 반영된다.
- `firestore.rules`를 바꿨다면 Firebase 콘솔/CLI로 별도 배포가 필요하다 (push로는 반영 안 됨).

## 데이터 규칙 (`transactions`)

- `unit_price`, `amount`, `realized_pnl`은 **항상 원화**로 저장한다. 하위 계산(holdings_calc 등)이
  전부 원화를 전제로 한다.
- 매도 거래는 `quantity`/`amount`를 **음수**로 저장한다 (매수=양수). 입력/수정 폼에서 금액을
  다시 계산할 때도 이 부호 규칙을 유지할 것.
- 해외 종목(`market: "해외"`)은 `unit_price_usd`, `fx_rate_used`를 **참고용으로만** 같이 기록한다.
  - 거래 입력(`add-transaction.html`): open.er-api.com의 오늘 환율
  - 거래일지 수정(`journal.html`): 기록된 `fx_rate_used` 우선, 없으면 frankfurter(ECB)의 **거래일** 환율
  - 환율 조회 실패 시 원화 직접 입력으로 돌아갈 수 있어야 한다.

## 코드 작성 시 주의

- **Python ↔ JS 중복 로직은 같이 고친다**: `src/holdings_calc.py` ↔ `web/holdings-calc.js`,
  `src/asset_classify.py` ↔ `web/asset-classify.js`. 한쪽만 바꾸면 웹과 리포트 숫자가 어긋난다.
- **투자 판단을 하드코딩하지 않는다.** 판단은 `claude -p` 세션이 WebSearch로 매번 새로 한다.
  코드는 무엇을 물어볼지(프롬프트 조립)와 결과 검증/저장만 담당한다.
- 모델 출력은 프롬프트로 지시하고, 중요한 규칙은 **코드에서도 한 번 더 강제**한다
  (예: 비반기 달 리밸런싱 비우기, ±5%p 허용 범위 필터).
- **Firestore 읽기 할당량**(무료 일 5만 건): 5분 주기 작업 등 자주 도는 코드에서
  `transactions` 전체를 스캔하지 말고 `settings/known_instruments` 캐시를 쓴다.
- **날짜는 KST로 명시 계산**한다. GitHub Actions 러너는 UTC라 `date.today()`를 쓰면 월 경계가 밀린다.
- 비밀값(`secrets/`)은 세션에서 `cat`하지 않는다 (대화 기록에 남음).

## 웹앱 (`web/`) 작성 규칙

- 빌드 도구 없는 정적 HTML + ES module. Firebase SDK는 gstatic CDN `10.12.2`를 import한다.
- 새 페이지를 만들면 기존 페이지처럼 `app-nav` 메뉴, `iaAuthed` 로그인 깜빡임 방지 스크립트,
  `pwa-register.js` import를 넣는다.
- 사용자 입력/DB 문자열을 HTML에 넣을 땐 `escapeHtml`(`charts.js`)을 쓴다.
- 모바일(iPhone Safari)에서 주로 쓴다:
  - `type=date` 입력은 `style.css`의 `appearance:none` 처리에 기대고 있다 - 패딩으로 땜질하지 말 것.
  - 폼은 `.form-grid` 2열을 유지한다 (모바일 1열 강제는 되돌렸음).
  - 넓은 테이블은 `overflow-x:auto` 래퍼로 감싸 가로 스크롤시킨다.
- 테스트 스위트는 없다. 최소한 인라인 module 스크립트를 뽑아 `node --check`로 문법을 확인하고,
  로그인이 필요한 화면은 실제 동작 확인을 사용자에게 요청한다.

## 결정해 둔 정책

- **리밸런싱 제안**: 반기 결산(6월/12월분 리포트, 즉 7월 초·1월 초 생성)에만 한다. 목표 비중과의
  차이가 **±5%p 이내**인 자산군은 제안하지 않는다(`REBALANCE_BAND_PP`). 국내주식/ETF는 정수
  주식수로, 10만원 미만 소액 매매는 제안하지 않는다.
- **급등락 알림**: 직전 대비 ±5% 이상, 현재 보유 중인 종목만.
