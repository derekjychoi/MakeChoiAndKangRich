"""매월 1일 실행: 4개 자산군(주식개별/ETF/금/코인) 비중을 현재 세계 경제/정치
상황에 비춰 어떻게 가져가면 좋을지 claude -p로 분석 요청해 monthly_reports
문서에 덧붙인다.

투자 판단 로직은 여기 하드코딩하지 않는다 - 매달 새로 스케줄된 Claude 세션이
WebSearch로 최신 정보를 찾아 직접 판단한다 (daily_run.sh와 동일한 철학).
이 스크립트 자체는 "무엇을 물어볼지"만 결정적으로 조립할 뿐이다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone

from asset_classify import classify_asset_class
from firestore_client import get_db
from send_telegram import escape_html, send_message

# WebFetch로 기사 원문까지 열어보게 하면서 300초로는 빠듯해져 넉넉히 늘림.
CLAUDE_TIMEOUT_SEC = 600
# 목표 비중과의 차이가 이 폭(%p) 이내인 자산군은 "허용 범위"로 보고 리밸런싱을 제안하지
# 않는다 - 시세 변동으로 생기는 작은 차이까지 맞추면 세금/수수료만 나가고 실익이 거의 없음.
REBALANCE_BAND_PP = 5.0
# 본문/JSON 뒤에 모델이 남기는 조사 기록(체크리스트별 찾은 값·출처, 실패한 검색어)의 구분선.
# 화면에 보이는 본문과 분리해 research_notes 필드로 따로 저장한다 (검증/디버깅용).
RESEARCH_NOTES_MARKER = "===RESEARCH_NOTES==="
# 본문 첫 줄 핵심 수치 요약에 반드시 있어야 하는 항목 (라벨 -> 프롬프트에서 지정한 표기).
# 값이 숫자로 없으면 1회 재시도, "확인 불가"면 재시도 없이 경고만 남긴다.
REQUIRED_SUMMARY_LABELS = {
    "美10년물 금리": "美10년물",
    "원/달러 환율": "원/달러",
    "금 가격": "금",
    "비트코인 가격": "BTC",
}
# 미래 날짜라도 이 단어가 근처에 있으면 예정된 일정(예: "다음 FOMC 12/9", "12/11까지의 임시예산")으로 보고
# 경고하지 않는다.
SCHEDULED_CONTEXT_WORDS = ("예정", "다음", "앞둔", "앞두고", "전망", "예상", "결과에 따라", "변곡점", "까지", "시한", "만료")
KST = timezone(timedelta(hours=9))


def _kst_today() -> date:
    """generate_monthly_report.py와 동일한 이유로 KST 기준 오늘을 명시적으로 계산한다
    (GitHub Actions 러너는 UTC라 date.today()를 쓰면 매월 1일 KST 실행 시 한 달 밀림)."""
    return datetime.now(KST).date()


def _prev_month_str(month_str: str) -> str:
    year, month = (int(x) for x in month_str.split("-"))
    first_of_month = date(year, month, 1)
    last_day_prev = first_of_month - timedelta(days=1)
    return f"{last_day_prev.year:04d}-{last_day_prev.month:02d}"


def _is_rebalance_month(month_str: str) -> bool:
    """리밸런싱 제안은 매달이 아니라 반기 결산(6월/12월)에만 한다 - 매달 제안하면
    너무 잦은 매매를 유도하기 쉽다는 피드백을 반영."""
    month = int(month_str.split("-")[1])
    return month in (6, 12)


def _current_allocation_pct(report: dict) -> dict[str, float]:
    breakdown = report.get("asset_class_breakdown", {})
    total_eval = report.get("total_eval_krw", 0) or 1
    return {cls: d["eval_krw"] / total_eval * 100 for cls, d in breakdown.items()}


def _filter_actions_within_band(
    report: dict, target_allocation: dict, actions: list[dict]
) -> tuple[list[dict], list[dict]]:
    """프롬프트로도 지시하지만, 모델이 허용 범위(±REBALANCE_BAND_PP) 안의 자산군까지
    매매를 제안했을 경우를 대비해 코드 레벨에서 한 번 더 걸러낸다.
    자산군을 판별할 수 없는 제안(목록에 없는 이름 등)은 임의로 버리지 않고 남긴다."""
    current = _current_allocation_pct(report)
    class_by_name = {h["name"]: classify_asset_class(h) for h in report.get("holdings_snapshot", [])}
    kept, dropped = [], []
    for a in actions:
        name = a.get("name", "") if isinstance(a, dict) else ""
        cls = name if name in target_allocation else class_by_name.get(name)
        target = target_allocation.get(cls) if cls else None
        if isinstance(target, (int, float)) and abs(target - current.get(cls, 0.0)) <= REBALANCE_BAND_PP:
            dropped.append(a)
        else:
            kept.append(a)
    return kept, dropped


def _breakdown_lines(report: dict) -> str:
    breakdown = report.get("asset_class_breakdown", {})
    total_eval = report.get("total_eval_krw", 0) or 1
    lines = []
    for cls, d in breakdown.items():
        pct_of_total = d["eval_krw"] / total_eval * 100
        profit_pct = ((d["eval_krw"] - d["invested_krw"]) / d["invested_krw"] * 100) if d.get("invested_krw") else 0
        lines.append(f"- {cls}: 비중 {pct_of_total:.1f}%, 평가금액 {d['eval_krw']:.0f}원, 누적수익률 {profit_pct:+.1f}%")
    return "\n".join(lines) if lines else "(보유 자산 없음)"


def _holdings_lines(report: dict) -> str:
    holdings = report.get("holdings_snapshot", [])
    if not holdings:
        return "(보유 종목 없음)"
    lines = []
    for h in sorted(holdings, key=lambda x: -x["eval_total_krw"]):
        cls = classify_asset_class(h)
        qty = h.get("quantity")
        price = h.get("current_price_krw")
        # 보유수량/현재가가 있으면 "몇 주를 얼마에" 수준까지 리밸런싱 제안이
        # 구체적일 수 있게 같이 넘긴다 (과거 스키마로 생성된 리포트는 없을 수 있음).
        qty_text = f"보유 {qty:g}주 @ {price:,.0f}원/주, " if qty is not None and price is not None else ""
        lines.append(
            f"- {h['name']} [{cls}]: {qty_text}평가금액 {h['eval_total_krw']:.0f}원, 수익률 {h['profit_pct']:+.1f}%"
        )
    return "\n".join(lines)


def _price_lines(report: dict, prev_report: dict | None) -> str:
    """리포트에 이미 있는 월말 종가(우리 데이터)를 "확인된 시세"로 넘긴다. 이걸 안 넘기면
    모델이 시세를 웹검색으로 다시 찾다가 실패하고 "현재 가격은 확인되지 않음"이라고 쓴다
    (실제로 2026-10 리포트에서 비트코인 가격을 그렇게 썼음)."""
    holdings = report.get("holdings_snapshot", [])
    prev_price_by_code = {
        h["code"]: h.get("current_price_krw")
        for h in (prev_report or {}).get("holdings_snapshot", [])
    }
    lines = []
    for h in sorted(holdings, key=lambda x: -x["eval_total_krw"]):
        price = h.get("current_price_krw")
        if price is None:
            continue
        prev_price = prev_price_by_code.get(h["code"])
        change_text = f", 전월말 대비 {(price / prev_price - 1) * 100:+.1f}%" if prev_price else ""
        lines.append(f"- {h['name']} [{classify_asset_class(h)}]: {price:,.0f}원{change_text}")
    return "\n".join(lines) if lines else "(시세 데이터 없음)"


def build_prompt(report: dict, prev_report: dict | None, include_rebalance: bool) -> str:
    breakdown_text = _breakdown_lines(report)
    holdings_text = _holdings_lines(report)
    price_text = _price_lines(report, prev_report)

    prev_section = ""
    if prev_report and prev_report.get("sector_allocation_advice"):
        prev_breakdown_text = _breakdown_lines(prev_report)
        prev_section = f"""
## 지난달({prev_report.get('month', '')}) 내가 제시했던 분석
{prev_report['sector_allocation_advice']}

## 지난달 시점 자산군별 누적수익률 (참고용, 위 분석 시점 기준)
{prev_breakdown_text}

위 지난달 분석에서 밝힌 "근거"가 이번 달 실제 시황 전개와 맞아떨어졌는지, 틀렸는지를
1~2문장으로 짧게 점검하라. 특히 **이번 달에 뒤집힌 근거가 있으면 반드시 명시**하라 (예:
"지난달 '대형지수 ETF는 안정적' 근거는 11/5 급락으로 빗나감"). 이번 달 조사로 후속 소식이
확인되지 않는 근거는 "확인 불가"라고 나열하지 말고 점검 대상에서 빼라. **중요: 이건 "그래서 오른 자산을 더 사자"는 식의 성과 추종이
아니라, 지난달 판단 논리 자체가 여전히 유효한지 자기점검하는 용도다.** 한 달치 손익은
자산배분 판단 근거로 쓰기엔 노이즈에 가까우니, 이번 달 새 추천은 어디까지나 최신 시황
재분석을 근거로 내리고, 지난달 점검 결과가 새 추천의 주된 근거가 되어서는 안 된다.
"""

    if include_rebalance:
        rebalance_section = """4. **마지막에 "결론: 목표 비중" 한 줄을 넣고, 네 자산군의 목표 비중을 합계 100%가 되도록
   구체적 숫자(%)로 제시하라.** 예시 형식: "결론: 목표 비중 — 주식(개별) 20% / 주식(ETF) 45% /
   금 10% / 코인 25%". 이 숫자는 정밀한 정답이 아니라 방향을 가늠하기 위한 참고 비율임을
   바로 다음 문장에서 짧게 밝혀라.
5. **그다음 "리밸런싱 제안" 한 단락을 추가하라.** 목표 비중에 맞추려면 위 "보유 종목 상세"
   목록 중 구체적으로 어떤 종목을 매도/매수하면 되는지 1~3개 실행 가능한 제안을 제시하라.
   - **허용 범위 규칙: 4번 목표 비중과 위 현재 비중의 차이가 ±{band:g}%p 이내인 자산군은
     매매를 제안하지 마라** (예: 목표 40%, 현재 43%면 차이 +3%p라 그대로 둔다). 차이가
     {band:g}%p를 넘는 자산군만 조정 대상이다. 제안할 때 해당 자산군의 "현재 → 목표" 비중을
     같이 적어라. 모든 자산군이 범위 안이면 "모든 자산군이 목표 ±{band:g}%p 이내라 이번
     반기는 리밸런싱이 필요 없음"이라고만 쓰고 제안은 하지 마라.
   - 반드시 위 목록에 실제로 있는 종목명만 사용하고, 목록에 없는 종목·티커를 지어내지 마라.
   - **국내 개별주식/ETF는 1주 단위로만 거래된다.** "약 100만원어치 매도"처럼 금액만
     제시하지 말고, 위에 적힌 보유수량/현재가를 근거로 "몇 주"인지 정수로 환산해서 제시하고
     괄호에 대략적 금액을 같이 적어라 (예: "SK하이닉스 3주 매도 (약 150만원, 1주 약 50만원
     기준)"). 보유수량보다 많은 주식수를 제안하지 마라.
   - 코인은 소수 단위 매매가 일반적이니 금액 기준으로 제시해도 된다. 해외주식은 소수점
     매매 가능 여부가 불확실하니 가능하면 정수 주 단위로, 어려우면 금액 기준도 허용한다.
   - 세금/수수료 때문에 실익이 없는 소액(대략 10만원 미만) 매매는 제안하지 마라.
   - 금액은 근사치임을 명시하고, 세금/수수료는 고려하지 않은 단순 참고용임을 밝혀라.
6. 형식: 순수 텍스트(HTML/마크다운 금지, 이모지와 줄바꿈만 사용). 총 1700자 이내로 간결하게.
7. 마지막 줄에 "※ 투자 판단은 참고용이며 최종 책임은 본인에게 있습니다." 를 반드시 포함하라.
8. 위 본문이 끝나면, 반드시 새 줄에 구분선 "===REBALANCE_JSON===" 을 쓰고, 그다음 줄부터
   4번의 목표 비중과 5번의 리밸런싱 제안을 아래 형식의 JSON **객체 하나**로 다시 한번
   구조화해서 출력하라 (자연어 설명 없이 JSON만):
   {
     "target_allocation": {"주식(개별)": 숫자, "주식(ETF)": 숫자, "금": 숫자, "코인": 숫자},
     "rebalancing_actions": [
       {"action": "매도" 또는 "매수", "name": "종목명 또는 자산군명(신규 자산군 매수 제안이면 자산군명 사용, 예: '금')", "quantity": 숫자(국내주식/ETF면 정수 주식수, 모르면 null), "amount_krw": 정수(대략적인 원화 금액, 모르면 null), "reason": "한 줄 이유"}
     ]
   }
   target_allocation의 네 값은 반드시 4번에서 제시한 숫자와 일치해야 하고 합계가 100이어야
   한다. rebalancing_actions에 제안이 없으면 빈 배열 []. 이 JSON 부분은 위 6번의 글자수
   제한과 무관하게 필요한 만큼 써도 된다.
9. JSON 다음에 새 줄로 "{notes_marker}" 를 쓰고 조사 기록을 남겨라 (아래 "조사 기록" 참고).
10. 출력은 본문 + JSON 구분선 + JSON + 조사 기록 구분선 + 조사 기록, 이 외에 서두 설명이나
   후기를 절대 넣지 마라. 본문에는 출처(Sources) 목록, "---" 구분선, 글자수 점검 메모,
   같은 본문 반복을 넣지 마라.""".replace(
            "{band:g}", f"{REBALANCE_BAND_PP:g}"
        )
    else:
        rebalance_section = """4. 목표 비중 숫자나 "리밸런싱 제안" 단락, JSON 블록은 **이번 달에는 작성하지 마라.**
   리밸런싱 제안은 반기(6월/12월 결산)에만 제시하며, 이번 달은 방향성 코멘트까지만 작성한다.
5. 형식: 순수 텍스트(HTML/마크다운 금지, 이모지와 줄바꿈만 사용). 총 1200자 이내로 간결하게.
6. 마지막 줄에 "※ 투자 판단은 참고용이며 최종 책임은 본인에게 있습니다." 를 반드시 포함하라.
7. 본문이 끝나면 새 줄에 "{notes_marker}" 를 쓰고 조사 기록을 남겨라 (아래 "조사 기록" 참고).
8. 출력은 본문 + 조사 기록 구분선 + 조사 기록뿐이다. 서두 설명이나 후기, JSON은 넣지 마라.
   본문에는 출처(Sources) 목록, "---" 구분선, 글자수 점검 메모, 같은 본문 반복을 넣지 마라."""

    rebalance_section = rebalance_section.replace("{notes_marker}", RESEARCH_NOTES_MARKER)

    return f"""너는 20년 경력의 개인 자산관리(웰스매니지먼트) 전문가다. 막연한 조언이 아니라
고객이 바로 실행할 수 있는 수준까지 구체적으로 짚어주는 게 네 역할이다.

## 현재 내 포트폴리오 자산군 비중 ({report.get('month', '')} 기준)
{breakdown_text}
총 평가금액: {report.get('total_eval_krw', 0):.0f}원

## 보유 종목 상세 (리밸런싱 제안 시 이 목록의 실제 종목명만 사용할 것)
{holdings_text}

## 확인된 시세 ({report.get('month', '')} 말 종가, 내 데이터 기준)
{price_text}
이 숫자는 이미 확인된 사실이다. 보유 종목 시세를 다시 검색하거나 "가격이 확인되지 않음"이라고
쓰지 말고, 가격·등락이 필요하면 이 값을 근거로 써라.
{prev_section}
## 조사 (필수 체크리스트)
아래는 "무엇을 찾을지"만 정한 목록이다. 무엇을 근거로 어떻게 판단할지는 네가 정한다.
WebSearch로 찾고, 검색 결과 요약만으로 부족하면 WebFetch로 기사/공식 발표 원문을 열어
확인하라. 기준 시점은 {report.get('month', '')} 말이다.

A. 매크로: 직전 FOMC 결과(금리 결정, 투표 결과, 점도표가 나온 회의면 점도표), 미국 10년물
   국채금리, 원/달러 환율, 국제유가(WTI 또는 브렌트) - 모두 {report.get('month', '')} 말 기준
B. 시장 월간 실측치({report.get('month', '')} 한 달): 금(USD/oz) 월말 가격, 비트코인(USD) 월말 가격,
   코스피·S&P500·나스닥 월간 등락률
C. 보유 종목 이슈: 위 "보유 종목 상세"의 종목마다 {report.get('month', '')} 주요 뉴스 1~2개 (ETF는 추종
   지수/테마 기준, 금 현물·코인은 B로 갈음해도 됨)
D. 그 외 지정학적 리스크·주요국 정책 등 이번 달 자산배분에 영향이 큰 이슈

"확인 불가" 규칙: A·B 항목은 검색어를 바꿔 2회 이상 시도해도 못 찾았을 때만 본문에
"확인 불가"로 짧게 쓴다. C·D에서 못 찾은 건 본문에서 아예 빼라.

## 작성 지침
0. 본문 맨 앞 두 줄에 A·B에서 찾은 핵심 수치를 **정확히 아래 형식**으로 요약하라 (라벨 표기를
   바꾸지 말 것 - 코드가 이 형식으로 누락 여부를 검사한다). 못 찾은 값은 "확인 불가"로 쓴다.
   📊 {report.get('month', '')} 말 | 美10년물 4.1% | 원/달러 1,380원 | 금 4,050달러 | BTC 98,000달러 | WTI 70달러
   📈 월간 | S&P500 -2.1% | 나스닥 -3.4% | 코스피 +1.2%
   본문은 곧바로 이 요약으로 시작하라 ("조사를 마쳤습니다" 같은 서두 금지).
   C의 종목 이슈는 판단에 영향이 있는 것만 해당 자산군 줄에 녹여 써라.
1. 위 정보를 종합해서, "주식(개별)/주식(ETF)/금/코인" 네 자산군의 비중을 지금보다
   늘리는 게 좋을지/줄이는 게 좋을지/유지가 좋을지 각각 한 줄씩 방향성과 이유를 제시하라.
   각 항목에 근거(예: "최근 금리 동향 기준", "지정학적 리스크 확대 국면")와 확인 시점을 명시하라.
2. **확인되지 않은 사실을 절대 추측하거나 지어내지 마라.** 다만 확인이 안 된 이슈를
   "확인되지 않음"이라고 하나하나 나열하지도 마라 - 그런 이슈는 아예 언급하지 말고,
   판단 근거는 이번 조사로 확인된 사실과 위 "확인된 시세"만으로 구성하라 (A·B 체크리스트
   항목만 위 "확인 불가" 규칙대로 예외). 확인된 근거가
   부족한 자산군은 "새 재료 부족, 유지" 정도로 짧게 쓰면 된다. 오래된 지식만으로 "최신"이라고
   단정하지 마라.
3. 확정적 지시가 아니라 참고 의견 톤으로 작성하라 (투자 책임은 본인에게 있음을 암시).
{rebalance_section}

## 조사 기록 (화면에 표시되지 않는 검증용 기록, 글자수 제한 없음)
"{RESEARCH_NOTES_MARKER}" 다음 줄부터 체크리스트 A~D 항목별로 찾은 값과 출처 URL을 한 줄씩
적어라. "확인 불가"로 처리한 항목은 시도한 검색어들을 같이 적어라. 순수 텍스트로.
"""


def _missing_summary_items(advice: str) -> tuple[list[str], list[str]]:
    """본문 첫 줄 요약에서 필수 수치가 (숫자로) 빠진 항목과 "확인 불가" 처리된 항목을 돌려준다."""
    summary = "\n".join(advice.splitlines()[:3])
    missing, unverified = [], []
    for name, label in REQUIRED_SUMMARY_LABELS.items():
        # "금"은 "금리" 같은 단어와 섞이지 않게 앞뒤가 한글이 아닐 때만 라벨로 본다.
        m = re.search(rf"(?<![가-힣]){re.escape(label)}(?![가-힣])\s*(확인\s*불가|[약~≈]?\s*\d)", summary)
        if not m:
            missing.append(name)
        elif m.group(1).replace(" ", "") == "확인불가":
            unverified.append(name)
    return missing, unverified


_FULL_DATE_RES = (
    re.compile(r"(20\d{2})[-./]\s?(\d{1,2})[-./]\s?(\d{1,2})"),
    re.compile(r"(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일"),
)
_MONTH_DAY_RES = (
    re.compile(r"(?<![\d/.\-])(\d{1,2})/(\d{1,2})(?![\d/])"),
    re.compile(r"(?<!\d)(\d{1,2})월\s*(\d{1,2})일"),
)


def _future_date_warnings(text: str, now: datetime) -> list[str]:
    """근거로 든 날짜가 생성 시각보다 뒤면 지어낸 근거일 가능성이 높다. 연도가 없는 "11/5" 같은
    표기는 생성 연도로 보되, 반년 넘게 미래면 작년 날짜(1월 리포트의 "12/28" 등)로 본다.
    "다음 FOMC 12/9"처럼 예정 일정을 말하는 경우는 근처 단어로 걸러낸다."""
    today = now.date()
    found: list[tuple[date, int, int]] = []
    masked = text
    for rx in _FULL_DATE_RES:
        for m in rx.finditer(masked):
            try:
                found.append((date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.start(), m.end()))
            except ValueError:
                continue
        masked = rx.sub(lambda m: " " * len(m.group(0)), masked)
    for rx in _MONTH_DAY_RES:
        for m in rx.finditer(masked):
            try:
                d = date(today.year, int(m.group(1)), int(m.group(2)))
            except ValueError:
                continue
            if (d - today).days > 180:
                d = d.replace(year=today.year - 1)
            found.append((d, m.start(), m.end()))

    warnings = []
    for d, start, end in sorted(found, key=lambda x: x[1]):
        if d <= today:
            continue
        # 예정 일정 판별은 같은 구절 안(문장부호/괄호 경계까지)에서만 본다 - 넓게 보면 옆 문장의
        # "다음"이나 "예정"까지 걸려 진짜 경고를 놓친다.
        before = re.split(r"[.,()|\n]", text[max(0, start - 15):start])[-1]
        after = re.split(r"[.,()|\n]", text[end:end + 15])[0]
        if any(w in before + after for w in SCHEDULED_CONTEXT_WORDS):
            continue
        context = text[max(0, start - 25):end + 25].replace("\n", " ")
        warnings.append(f"생성일({today}) 이후 날짜 {d}: …{context.strip()}…")
    return warnings


def _run_claude(prompt: str) -> str:
    try:
        result = subprocess.run(
            # --tools로 쓸 수 있는 도구 자체를 웹 조사로 한정한다. 안 그러면 모델이 글자수를
            # 세려고 Bash/Write를 시도하다 권한 거부되고, 그 여파로 본문이 중복 출력됐음.
            ["claude", "-p", prompt, "--model", "claude-sonnet-5",
             "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch",
             "--output-format", "text"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(f"claude -p가 {CLAUDE_TIMEOUT_SEC}초 내 응답 없음 (인증 토큰 만료 가능성)")

    raw = result.stdout.strip()
    if result.returncode != 0 or not raw:
        raise SystemExit(f"claude -p 실패 (exit={result.returncode}): {result.stderr[:500]}")
    return raw


def _split_output(raw: str) -> tuple[str, dict, list[dict], str]:
    body, _, research_notes = raw.partition(RESEARCH_NOTES_MARKER)
    advice, target_allocation, rebalancing_actions = _split_advice_and_json(body.strip())
    return advice, target_allocation, rebalancing_actions, research_notes.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="대상 월 YYYY-MM (기본값: 지난달)")
    parser.add_argument(
        "--force-rebalance", action="store_true",
        help="반기(6월/12월)가 아니어도 리밸런싱 제안을 강제로 포함 (수동 실행용)",
    )
    args = parser.parse_args()

    db = get_db()

    if args.month:
        month = args.month
    else:
        today = _kst_today()
        today_str = f"{today.year:04d}-{today.month:02d}"
        month = _prev_month_str(today_str)

    doc_ref = db.collection("monthly_reports").document(month)
    report = doc_ref.get().to_dict()
    if not report:
        raise SystemExit(f"monthly_reports/{month} 문서가 없습니다. generate_monthly_report.py를 먼저 실행하세요.")

    prev_month = _prev_month_str(month)
    prev_report = db.collection("monthly_reports").document(prev_month).get().to_dict()

    include_rebalance = args.force_rebalance or _is_rebalance_month(month)
    prompt = build_prompt(report, prev_report, include_rebalance)

    advice, target_allocation, rebalancing_actions, research_notes = _split_output(_run_claude(prompt))
    missing, unverified = _missing_summary_items(advice)
    if missing:
        # 필수 수치가 빠지면 빠진 항목을 짚어 1회 재시도하고, 누락이 더 적은 쪽을 쓴다.
        print(f"필수 수치 누락 {missing} - 1회 재시도")
        retry_prompt = (
            f"{prompt}\n\n## 재요청\n직전 응답의 첫 줄 핵심 수치 요약에서 {', '.join(missing)}이(가) "
            "빠졌다. 이 항목을 반드시 조사해서 작성 지침 0번 형식 그대로 채워라 "
            '(검색어를 바꿔 2회 이상 시도해도 못 찾으면 "확인 불가").'
        )
        retried = _split_output(_run_claude(retry_prompt))
        retry_missing, retry_unverified = _missing_summary_items(retried[0])
        if len(retry_missing) < len(missing):
            advice, target_allocation, rebalancing_actions, research_notes = retried
            missing, unverified = retry_missing, retry_unverified

    generated_at = datetime.now(KST)
    warnings = [f"필수 수치 누락: {name}" for name in missing]
    warnings += [f"필수 수치 확인 불가: {name}" for name in unverified]
    warnings += _future_date_warnings(f"{advice}\n{research_notes}", generated_at)
    if not include_rebalance:
        # 프롬프트에서 JSON을 쓰지 말라고 했지만, 혹시 모델이 지침을 어기고
        # 끼워 넣었을 경우를 대비해 비반기 달은 코드 레벨에서도 강제로 비운다.
        target_allocation, rebalancing_actions = {}, []
    else:
        rebalancing_actions, dropped = _filter_actions_within_band(report, target_allocation, rebalancing_actions)
        if dropped:
            print(
                f"허용 범위(±{REBALANCE_BAND_PP:g}%p) 안 자산군 제안 {len(dropped)}건 제외: "
                + ", ".join(f"{a.get('action', '')} {a.get('name', '')}" for a in dropped)
            )

    doc_ref.set({
        "sector_allocation_advice": advice,
        "target_allocation": target_allocation,
        "rebalancing_actions": rebalancing_actions,
        "research_notes": research_notes,
        # generated_at(월간 리포트 숫자 생성 시각)과 별개로, 의견을 실제로 만든 시각과 검증 결과를 남긴다.
        "advice_generated_at": generated_at.isoformat(),
        "validation_warnings": warnings,
    }, merge=True)
    print(
        f"저장 완료: monthly_reports/{month}.sector_allocation_advice ({len(advice)}자), "
        f"리밸런싱 포함={include_rebalance}, target_allocation={target_allocation}, "
        f"rebalancing_actions {len(rebalancing_actions)}건, research_notes {len(research_notes)}자"
    )
    if warnings:
        print("!!! 검증 경고:\n" + "\n".join(f"- {w}" for w in warnings))
        try:
            send_message(
                f"⚠️ {escape_html(month)} 자산배분 의견 검증 경고 {len(warnings)}건\n"
                + "\n".join(f"- {escape_html(w)}" for w in warnings[:10])
            )
        except Exception as err:  # 알림 실패가 저장된 리포트를 무르게 하지는 않는다
            print(f"검증 경고 텔레그램 발송 실패: {err}")


def _split_advice_and_json(raw: str) -> tuple[str, dict, list[dict]]:
    marker = "===REBALANCE_JSON==="
    if marker not in raw:
        return raw, {}, []

    narrative, _, json_part = raw.partition(marker)
    narrative = narrative.strip()

    start = json_part.find("{")
    end = json_part.rfind("}")
    if start == -1 or end == -1 or end < start:
        return narrative, {}, []

    try:
        parsed = json.loads(json_part[start:end + 1])
        if not isinstance(parsed, dict):
            return narrative, {}, []
        target_allocation = parsed.get("target_allocation", {})
        rebalancing_actions = parsed.get("rebalancing_actions", [])
        if not isinstance(target_allocation, dict):
            target_allocation = {}
        if not isinstance(rebalancing_actions, list):
            rebalancing_actions = []
        return narrative, target_allocation, rebalancing_actions
    except json.JSONDecodeError:
        return narrative, {}, []


if __name__ == "__main__":
    main()
