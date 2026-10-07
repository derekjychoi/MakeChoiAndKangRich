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
import subprocess
from datetime import date, datetime, timedelta, timezone

from asset_classify import classify_asset_class
from firestore_client import get_db

CLAUDE_TIMEOUT_SEC = 300
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


def build_prompt(report: dict, prev_report: dict | None, include_rebalance: bool) -> str:
    breakdown_text = _breakdown_lines(report)
    holdings_text = _holdings_lines(report)

    prev_section = ""
    if prev_report and prev_report.get("sector_allocation_advice"):
        prev_breakdown_text = _breakdown_lines(prev_report)
        prev_section = f"""
## 지난달({prev_report.get('month', '')}) 내가 제시했던 분석
{prev_report['sector_allocation_advice']}

## 지난달 시점 자산군별 누적수익률 (참고용, 위 분석 시점 기준)
{prev_breakdown_text}

위 지난달 분석에서 밝힌 "근거"가 이번 달 실제 시황 전개와 맞아떨어졌는지, 틀렸는지를
1~2문장으로 짧게 점검하라. **중요: 이건 "그래서 오른 자산을 더 사자"는 식의 성과 추종이
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
   - 반드시 위 목록에 실제로 있는 종목명만 사용하고, 목록에 없는 종목·티커를 지어내지 마라.
   - **국내 개별주식/ETF는 1주 단위로만 거래된다.** "약 100만원어치 매도"처럼 금액만
     제시하지 말고, 위에 적힌 보유수량/현재가를 근거로 "몇 주"인지 정수로 환산해서 제시하고
     괄호에 대략적 금액을 같이 적어라 (예: "SK하이닉스 3주 매도 (약 150만원, 1주 약 50만원
     기준)"). 보유수량보다 많은 주식수를 제안하지 마라.
   - 코인은 소수 단위 매매가 일반적이니 금액 기준으로 제시해도 된다. 해외주식은 소수점
     매매 가능 여부가 불확실하니 가능하면 정수 주 단위로, 어려우면 금액 기준도 허용한다.
   - 세금/수수료 때문에 실익이 없는 소액(대략 10만원 미만) 매매는 제안하지 마라.
   - 금액은 근사치임을 명시하고, 세금/수수료는 고려하지 않은 단순 참고용임을 밝혀라.
6. 형식: 순수 텍스트(HTML/마크다운 금지, 이모지와 줄바꿈만 사용). 총 1400자 이내로 간결하게.
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
9. 출력은 본문 + 구분선 + JSON, 이 세 부분 외에 서두 설명이나 후기를 절대 넣지 마라."""
    else:
        rebalance_section = """4. 목표 비중 숫자나 "리밸런싱 제안" 단락, JSON 블록은 **이번 달에는 작성하지 마라.**
   리밸런싱 제안은 반기(6월/12월 결산)에만 제시하며, 이번 달은 방향성 코멘트까지만 작성한다.
5. 형식: 순수 텍스트(HTML/마크다운 금지, 이모지와 줄바꿈만 사용). 총 900자 이내로 간결하게.
6. 마지막 줄에 "※ 투자 판단은 참고용이며 최종 책임은 본인에게 있습니다." 를 반드시 포함하라.
7. 서두 설명이나 후기 없이 본문만 출력하고, 구분선이나 JSON은 절대 포함하지 마라."""

    return f"""너는 20년 경력의 개인 자산관리(웰스매니지먼트) 전문가다. 막연한 조언이 아니라
고객이 바로 실행할 수 있는 수준까지 구체적으로 짚어주는 게 네 역할이다.

## 현재 내 포트폴리오 자산군 비중 ({report.get('month', '')} 기준)
{breakdown_text}
총 평가금액: {report.get('total_eval_krw', 0):.0f}원

## 보유 종목 상세 (리밸런싱 제안 시 이 목록의 실제 종목명만 사용할 것)
{holdings_text}
{prev_section}
## 조사
WebSearch로 오늘 기준 세계 경제/정치 상황(금리, 인플레이션, 지정학적 리스크,
주요국 정책 등) 최신 정보를 확인하라.

## 작성 지침
1. 위 정보를 종합해서, "주식(개별)/주식(ETF)/금/코인" 네 자산군의 비중을 지금보다
   늘리는 게 좋을지/줄이는 게 좋을지/유지가 좋을지 각각 한 줄씩 방향성과 이유를 제시하라.
   각 항목에 근거(예: "최근 금리 동향 기준", "지정학적 리스크 확대 국면")와 확인 시점을 명시하라.
2. **확인되지 않은 사실을 절대 추측하거나 지어내지 마라.** WebSearch로 확인이 안 되는
   내용은 "확인되지 않음" 또는 "일반적인 트렌드로만 알려짐"이라고 명확히 밝히고,
   불확실한 걸 확정적으로 말하지 마라. 오래된 지식만으로 "최신"이라고 단정하지 마라.
3. 확정적 지시가 아니라 참고 의견 톤으로 작성하라 (투자 책임은 본인에게 있음을 암시).
{rebalance_section}
"""


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

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "claude-sonnet-5",
             "--allowedTools", "WebSearch", "--output-format", "text"],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(f"claude -p가 {CLAUDE_TIMEOUT_SEC}초 내 응답 없음 (인증 토큰 만료 가능성)")

    raw = result.stdout.strip()
    if result.returncode != 0 or not raw:
        raise SystemExit(f"claude -p 실패 (exit={result.returncode}): {result.stderr[:500]}")

    advice, target_allocation, rebalancing_actions = _split_advice_and_json(raw)
    if not include_rebalance:
        # 프롬프트에서 JSON을 쓰지 말라고 했지만, 혹시 모델이 지침을 어기고
        # 끼워 넣었을 경우를 대비해 비반기 달은 코드 레벨에서도 강제로 비운다.
        target_allocation, rebalancing_actions = {}, []

    doc_ref.set({
        "sector_allocation_advice": advice,
        "target_allocation": target_allocation,
        "rebalancing_actions": rebalancing_actions,
    }, merge=True)
    print(
        f"저장 완료: monthly_reports/{month}.sector_allocation_advice ({len(advice)}자), "
        f"리밸런싱 포함={include_rebalance}, target_allocation={target_allocation}, "
        f"rebalancing_actions {len(rebalancing_actions)}건"
    )


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
