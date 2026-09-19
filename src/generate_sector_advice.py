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
from datetime import date, timedelta

from asset_classify import classify_asset_class
from firestore_client import get_db

CLAUDE_TIMEOUT_SEC = 300


def _prev_month_str(month_str: str) -> str:
    year, month = (int(x) for x in month_str.split("-"))
    first_of_month = date(year, month, 1)
    last_day_prev = first_of_month - timedelta(days=1)
    return f"{last_day_prev.year:04d}-{last_day_prev.month:02d}"


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
        lines.append(
            f"- {h['name']} [{cls}]: 평가금액 {h['eval_total_krw']:.0f}원, 수익률 {h['profit_pct']:+.1f}%"
        )
    return "\n".join(lines)


def build_prompt(report: dict, prev_report: dict | None) -> str:
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

    return f"""너는 개인 투자자의 자산배분을 조언하는 애널리스트다.

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
4. **마지막에 "결론: 목표 비중" 한 줄을 넣고, 네 자산군의 목표 비중을 합계 100%가 되도록
   구체적 숫자(%)로 제시하라.** 예시 형식: "결론: 목표 비중 — 주식(개별) 20% / 주식(ETF) 45% /
   금 10% / 코인 25%". 이 숫자는 정밀한 정답이 아니라 방향을 가늠하기 위한 참고 비율임을
   바로 다음 문장에서 짧게 밝혀라.
5. **그다음 "리밸런싱 제안" 한 단락을 추가하라.** 목표 비중에 맞추려면 위 "보유 종목 상세"
   목록 중 구체적으로 어떤 종목을 얼마나(대략적인 금액/비중) 매도하고, 그 돈으로 어떤
   종목/자산군을 매수하면 되는지 1~3개 실행 가능한 제안을 제시하라. 반드시 위 목록에
   실제로 있는 종목명만 사용하고, 목록에 없는 종목·티커를 지어내지 마라. 금액은 대략적인
   근사치임을 명시하고, 세금/수수료는 고려하지 않은 단순 참고용임을 밝혀라.
6. 형식: 순수 텍스트(HTML/마크다운 금지, 이모지와 줄바꿈만 사용). 총 1400자 이내로 간결하게.
7. 마지막 줄에 "※ 투자 판단은 참고용이며 최종 책임은 본인에게 있습니다." 를 반드시 포함하라.
8. 위 본문이 끝나면, 반드시 새 줄에 구분선 "===REBALANCE_JSON===" 을 쓰고, 그다음 줄부터
   5번의 리밸런싱 제안을 JSON 배열로 다시 한번 구조화해서 출력하라 (자연어 설명 없이
   JSON 배열만). 각 항목은 정확히 이 키를 가져야 한다:
   {{"action": "매도" 또는 "매수", "name": "종목명 또는 자산군명(신규 자산군 매수 제안이면 자산군명 사용, 예: '금')", "amount_krw": 정수(대략적인 원화 금액, 모르면 null), "reason": "한 줄 이유"}}
   제안이 없으면 빈 배열 []을 출력하라. 이 JSON 부분은 위 6번의 글자수 제한과 무관하게
   필요한 만큼 써도 된다.
9. 출력은 본문 + 구분선 + JSON, 이 세 부분 외에 서두 설명이나 후기를 절대 넣지 마라.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="대상 월 YYYY-MM (기본값: 지난달)")
    args = parser.parse_args()

    db = get_db()

    if args.month:
        month = args.month
    else:
        today_str = f"{date.today().year:04d}-{date.today().month:02d}"
        month = _prev_month_str(today_str)

    doc_ref = db.collection("monthly_reports").document(month)
    report = doc_ref.get().to_dict()
    if not report:
        raise SystemExit(f"monthly_reports/{month} 문서가 없습니다. generate_monthly_report.py를 먼저 실행하세요.")

    prev_month = _prev_month_str(month)
    prev_report = db.collection("monthly_reports").document(prev_month).get().to_dict()

    prompt = build_prompt(report, prev_report)

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

    advice, rebalancing_actions = _split_advice_and_json(raw)

    doc_ref.set({
        "sector_allocation_advice": advice,
        "rebalancing_actions": rebalancing_actions,
    }, merge=True)
    print(
        f"저장 완료: monthly_reports/{month}.sector_allocation_advice ({len(advice)}자), "
        f"rebalancing_actions {len(rebalancing_actions)}건"
    )


def _split_advice_and_json(raw: str) -> tuple[str, list[dict]]:
    marker = "===REBALANCE_JSON==="
    if marker not in raw:
        return raw, []

    narrative, _, json_part = raw.partition(marker)
    narrative = narrative.strip()

    start = json_part.find("[")
    end = json_part.rfind("]")
    if start == -1 or end == -1 or end < start:
        return narrative, []

    try:
        actions = json.loads(json_part[start:end + 1])
        if not isinstance(actions, list):
            return narrative, []
        return narrative, actions
    except json.JSONDecodeError:
        return narrative, []


if __name__ == "__main__":
    main()
