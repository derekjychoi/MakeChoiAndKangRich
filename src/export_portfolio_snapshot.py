"""daily_run.sh용: Firestore(transactions + latest_prices)를 기존
data/portfolio_snapshot.json 형식으로 내보낸다.

구글시트 fetch_portfolio.py를 대체한다 - Firestore가 거래 내역의 원본이 된 뒤로는
daily_run.sh가 매일 최신 시세로 스냅샷을 다시 만들어 텔레그램 프롬프트에 쓴다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from config import PORTFOLIO_SNAPSHOT_PATH, ensure_data_dir
from firestore_client import get_db
from holdings_calc import apply_prices, compute_holdings


def main() -> None:
    db = get_db()
    transactions = [doc.to_dict() for doc in db.collection("transactions").stream()]
    price_map = {doc.id: doc.to_dict() for doc in db.collection("latest_prices").stream()}

    transactions.sort(key=lambda t: t["date"])
    holdings = compute_holdings(transactions)
    apply_prices(holdings, price_map)
    holdings.sort(key=lambda h: h["eval_total_krw"], reverse=True)

    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "transactions": transactions,
        "holdings": holdings,
    }

    ensure_data_dir()
    PORTFOLIO_SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"저장 완료: {PORTFOLIO_SNAPSHOT_PATH} "
        f"(transactions={len(transactions)}, holdings={len(holdings)})"
    )


if __name__ == "__main__":
    main()
