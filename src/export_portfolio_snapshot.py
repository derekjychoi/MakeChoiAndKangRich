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

    # 웹 입력 폼이 저장하는 created_at(Firestore 타임스탬프)/created_by는 텔레그램
    # 브리핑 프롬프트에 필요 없고, 그대로 두면 JSON 직렬화가 안 돼서 제거한다.
    for t in transactions:
        t.pop("created_at", None)
        t.pop("created_by", None)

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
        # default=str: 혹시 모를 다른 Firestore 전용 타입(타임스탬프 등)이 섞여도
        # 죽지 않고 문자열로 대체하는 방어용
        json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        f"저장 완료: {PORTFOLIO_SNAPSHOT_PATH} "
        f"(transactions={len(transactions)}, holdings={len(holdings)})"
    )


if __name__ == "__main__":
    main()
