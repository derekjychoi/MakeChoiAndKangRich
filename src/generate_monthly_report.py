"""매월 1일 실행: 전달(previous month) 거래 내역을 집계해 Firestore에 저장한다.

결정적 통계 집계만 수행한다 (투자 판단 로직 없음).
거래 내역 원본은 Firestore `transactions` 컬렉션(웹에서 입력).
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from asset_classify import classify_asset_class
from firestore_client import get_db
from historical_prices import fetch_historical_price_map
from holdings_calc import apply_prices, compute_holdings


def _prev_month(today: date) -> tuple[int, int]:
    first_of_this_month = today.replace(day=1)
    last_day_prev = first_of_this_month - timedelta(days=1)
    return last_day_prev.year, last_day_prev.month


def _last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def build_report(transactions: list[dict], holdings: list[dict], year: int, month: int) -> dict[str, Any]:
    month_str = f"{year:04d}-{month:02d}"
    month_txns = [t for t in transactions if t["date"].startswith(month_str)]

    # 매도 거래의 amount는 이미 음수로 저장돼 있다 (매수=양수, 매도=음수).
    total_buy = sum(t["amount"] for t in month_txns if t["type"] == "매수")
    total_sell = -sum(t["amount"] for t in month_txns if t["type"] == "매도")  # 표시용 양수 크기
    realized_pnl = sum(t.get("realized_pnl", 0) for t in month_txns)

    net_flow_by_broker: dict[str, float] = defaultdict(float)
    net_flow_by_sector: dict[str, float] = defaultdict(float)
    for t in month_txns:
        net_flow_by_broker[t["broker"]] += t["amount"]
        net_flow_by_sector[t["sector"]] += t["amount"]

    holdings_snapshot = [
        {
            "name": h["name"],
            "sector": h["sector"],
            "code": h["code"],
            "eval_total_krw": h["eval_total_krw"],
            "profit_krw": h["profit_krw"],
            "profit_pct": h["profit_pct"],
        }
        for h in holdings
    ]

    asset_class_breakdown: dict[str, dict[str, float]] = defaultdict(lambda: {"eval_krw": 0.0, "invested_krw": 0.0})
    for h in holdings:
        cls = asset_class_breakdown[classify_asset_class(h)]
        cls["eval_krw"] += h["eval_total_krw"]
        cls["invested_krw"] += h["total_buy_krw"]

    total_invested = sum(h["total_buy_krw"] for h in holdings)
    total_unrealized_profit = sum(h["profit_krw"] for h in holdings)
    overall_profit_pct = (total_unrealized_profit / total_invested * 100) if total_invested else 0.0

    return {
        "month": month_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trade_count": len(month_txns),
        "total_buy_krw": total_buy,
        "total_sell_krw": total_sell,
        "realized_pnl_krw": realized_pnl,
        "net_flow_by_broker_krw": dict(net_flow_by_broker),
        "net_flow_by_sector_krw": dict(net_flow_by_sector),
        "holdings_snapshot": holdings_snapshot,
        "asset_class_breakdown": {k: dict(v) for k, v in asset_class_breakdown.items()},
        "total_eval_krw": sum(h["eval_total_krw"] for h in holdings),
        "total_invested_krw": total_invested,
        "total_unrealized_profit_krw": total_unrealized_profit,
        "overall_profit_pct": overall_profit_pct,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="집계 대상 월, YYYY-MM 형식 (기본값: 지난달)")
    args = parser.parse_args()

    if args.month:
        year, month = (int(x) for x in args.month.split("-"))
    else:
        year, month = _prev_month(date.today())

    month_str = f"{year:04d}-{month:02d}"
    today = date.today()
    current_month_str = f"{today.year:04d}-{today.month:02d}"
    if month_str >= current_month_str:
        raise SystemExit(
            f"{month_str}는 아직 끝나지 않은 달입니다 (오늘: {current_month_str}). "
            "월간 리포트는 끝난 달만 생성합니다."
        )

    as_of = _last_day_of_month(year, month)

    db = get_db()
    all_transactions = [doc.to_dict() for doc in db.collection("transactions").stream()]
    # 그 달 말 시점 보유 현황은 그 시점까지의 거래만 반영해야 한다 (이후 거래 제외).
    transactions_up_to_as_of = [t for t in all_transactions if t["date"] <= as_of.isoformat()]

    holdings = compute_holdings(transactions_up_to_as_of)
    price_map = fetch_historical_price_map(transactions_up_to_as_of, as_of)
    apply_prices(holdings, price_map)

    report = build_report(all_transactions, holdings, year, month)
    db.collection("monthly_reports").document(report["month"]).set(report)

    print(f"저장 완료: monthly_reports/{report['month']} ({as_of} 기준 시세, 거래 {report['trade_count']}건)")


if __name__ == "__main__":
    main()
