"""거래 내역(transactions)으로부터 보유 종목(holdings)을 계산한다.

평균단가법(average cost method)을 사용한다: 매수 시 총원가에 더하고,
매도 시 매도 시점의 평균단가만큼 총원가에서 차감한다.

주의: 원본 데이터는 매도 거래의 quantity/amount를 이미 음수로 저장한다
(매수는 양수, 매도는 음수인 부호 있는 값). quantity는 그대로 더하면 되고,
원가 차감만 "매도 수량(절대값) x 매도 시점 평균단가"로 별도 계산해야 한다
(매도 시 받은 금액이 아니라 원가를 차감해야 실현손익이 원가에 섞이지 않는다).
"""
from __future__ import annotations


def compute_holdings(transactions: list[dict]) -> list[dict]:
    by_code: dict[str, dict] = {}
    for t in sorted(transactions, key=lambda x: x["date"]):
        code = t["code"]
        h = by_code.setdefault(code, {
            "code": code, "name": t["name"], "sector": t["sector"],
            "market": t.get("market", ""), "quantity": 0.0, "total_cost": 0.0,
        })
        h["name"] = t["name"]
        h["sector"] = t["sector"]
        if t["type"] == "매수":
            h["total_cost"] += t["amount"]
            h["quantity"] += t["quantity"]
        else:
            sold_qty = abs(t["quantity"])
            if h["quantity"] > 0:
                avg_cost = h["total_cost"] / h["quantity"]
                h["total_cost"] -= avg_cost * sold_qty
            h["quantity"] += t["quantity"]  # 이미 음수이므로 더하면 줄어든다

    holdings = []
    for h in by_code.values():
        if h["quantity"] <= 1e-9:
            continue
        avg_buy_price = h["total_cost"] / h["quantity"] if h["quantity"] else 0.0
        holdings.append({
            "name": h["name"],
            "sector": h["sector"],
            "code": h["code"],
            "market": h["market"],
            "quantity": h["quantity"],
            "avg_buy_price_krw": avg_buy_price,
            "total_buy_krw": h["total_cost"],
        })
    return holdings


def apply_prices(holdings: list[dict], price_map: dict[str, dict]) -> list[dict]:
    """price_map: {code: {"price_krw": float, ...}}. 시세 없으면 평단가로 대체(손익 0으로 표시)."""
    for h in holdings:
        price_info = price_map.get(h["code"])
        current_price = price_info["price_krw"] if price_info else h["avg_buy_price_krw"]
        h["current_price_krw"] = current_price
        h["price_is_live"] = bool(price_info)
        h["eval_total_krw"] = h["quantity"] * current_price
        h["profit_krw"] = h["eval_total_krw"] - h["total_buy_krw"]
        h["profit_pct"] = (h["profit_krw"] / h["total_buy_krw"] * 100) if h["total_buy_krw"] else 0.0
    return holdings
