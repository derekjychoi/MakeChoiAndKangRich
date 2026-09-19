"""1회성 마이그레이션: 기존 구글시트 스냅샷(data/portfolio_snapshot.json)의
거래 내역을 Firestore `transactions` 컬렉션으로 옮긴다.

문서ID는 거래 필드 해시로 고정해서, 다시 실행해도 중복 저장되지 않는다(멱등).
이후로는 구글시트가 아니라 Firestore가 거래 내역의 원본이 된다.
"""
from __future__ import annotations

import hashlib
import json

from config import PORTFOLIO_SNAPSHOT_PATH
from firestore_client import get_db


def _doc_id(t: dict) -> str:
    key = f"{t['date']}|{t['broker']}|{t['type']}|{t['code']}|{t['quantity']}|{t['amount']}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def main() -> None:
    snapshot = json.loads(PORTFOLIO_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    transactions = snapshot["transactions"]

    db = get_db()
    batch = db.batch()
    coll = db.collection("transactions")
    written = 0

    for i, t in enumerate(transactions):
        doc_id = _doc_id(t)
        doc_ref = coll.document(doc_id)
        payload = {**t, "migrated_from_sheet": True}
        batch.set(doc_ref, payload, merge=True)
        written += 1
        if (i + 1) % 400 == 0:
            batch.commit()
            batch = db.batch()

    batch.commit()
    print(f"마이그레이션 완료: {written}건 -> transactions 컬렉션 (문서ID는 내용 해시라 재실행해도 안전)")


if __name__ == "__main__":
    main()
