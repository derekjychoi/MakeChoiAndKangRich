// src/holdings_calc.py 와 동일한 평균단가법 로직의 JS 포팅본.

export function computeHoldings(transactions) {
  const byCode = new Map();
  const sorted = [...transactions].sort((a, b) => (a.date < b.date ? -1 : 1));

  for (const t of sorted) {
    if (!byCode.has(t.code)) {
      byCode.set(t.code, {
        code: t.code, name: t.name, sector: t.sector, market: t.market || "",
        quantity: 0, totalCost: 0,
      });
    }
    const h = byCode.get(t.code);
    h.name = t.name;
    h.sector = t.sector;
    // 매도 거래는 quantity/amount가 이미 음수로 저장돼 있다.
    if (t.type === "매수") {
      h.totalCost += t.amount;
      h.quantity += t.quantity;
    } else {
      const soldQty = Math.abs(t.quantity);
      if (h.quantity > 0) {
        const avgCost = h.totalCost / h.quantity;
        h.totalCost -= avgCost * soldQty;
      }
      h.quantity += t.quantity; // 이미 음수이므로 더하면 줄어든다
    }
  }

  const holdings = [];
  for (const h of byCode.values()) {
    if (h.quantity <= 1e-9) continue;
    const avgBuyPrice = h.quantity ? h.totalCost / h.quantity : 0;
    holdings.push({
      name: h.name, sector: h.sector, code: h.code, market: h.market,
      quantity: h.quantity,
      avg_buy_price_krw: avgBuyPrice,
      total_buy_krw: h.totalCost,
    });
  }
  return holdings;
}

export function applyPrices(holdings, priceMap) {
  for (const h of holdings) {
    const priceInfo = priceMap[h.code];
    const currentPrice = priceInfo ? priceInfo.price_krw : h.avg_buy_price_krw;
    h.current_price_krw = currentPrice;
    h.price_is_live = Boolean(priceInfo);
    h.eval_total_krw = h.quantity * currentPrice;
    h.profit_krw = h.eval_total_krw - h.total_buy_krw;
    h.profit_pct = h.total_buy_krw ? (h.profit_krw / h.total_buy_krw) * 100 : 0;
  }
  return holdings;
}
