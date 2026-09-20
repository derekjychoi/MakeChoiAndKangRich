"""transactions 컬렉션에 등장하는 모든 종목의 실시간(근사) 시세를 조회해
latest_prices 컬렉션에 저장한다.

- 국내주식/ETF (6자리 숫자 코드): 네이버 시세 폴링 API
- 해외 티커 (TQQQ 등): 야후 파이낸스 (USD -> KRW 환율 적용)
- 코인 (BTC/ETH/XRP 등): 업비트 공개 시세 API
- 금 현물 등 미지원 자산: 건너뜀 (holdings_calc가 평단가로 대체 처리)

직전 조회 시점 대비 ALERT_THRESHOLD_PCT 이상 급등/급락하면 텔레그램으로 알린다.

GitHub Actions로 15분 간격 반복 실행된다. 웹페이지는 이 컬렉션을 실시간 구독한다.
"""
from __future__ import annotations

import requests
from firebase_admin import firestore

import send_telegram
from asset_classify import classify_price_source
from firestore_client import get_db

ALERT_THRESHOLD_PCT = 5.0

NAVER_URL = "https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_FX_URL = "https://query1.finance.yahoo.com/v8/finance/chart/KRW=X"
UPBIT_URL = "https://api.upbit.com/v1/ticker"
HEADERS = {"User-Agent": "Mozilla/5.0"}

_usdkrw_cache: float | None = None


def fetch_naver_kr(code: str) -> float | None:
    try:
        r = requests.get(NAVER_URL.format(code=code), headers=HEADERS, timeout=5)
        r.raise_for_status()
        close = r.json()["datas"][0]["closePrice"]
        return float(str(close).replace(",", ""))
    except Exception:
        return None


def _usdkrw() -> float | None:
    global _usdkrw_cache
    if _usdkrw_cache is not None:
        return _usdkrw_cache
    try:
        r = requests.get(YAHOO_FX_URL, headers=HEADERS, timeout=5)
        r.raise_for_status()
        _usdkrw_cache = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return _usdkrw_cache
    except Exception:
        return None


def fetch_yahoo_us(ticker: str) -> float | None:
    try:
        r = requests.get(YAHOO_URL.format(ticker=ticker), headers=HEADERS, timeout=5)
        r.raise_for_status()
        price_usd = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
        rate = _usdkrw()
        return price_usd * rate if rate else None
    except Exception:
        return None


def fetch_upbit_crypto(code: str) -> float | None:
    try:
        r = requests.get(UPBIT_URL, params={"markets": f"KRW-{code.upper()}"}, headers=HEADERS, timeout=5)
        r.raise_for_status()
        return float(r.json()[0]["trade_price"])
    except Exception:
        return None


FETCHERS = {
    "naver_kr": fetch_naver_kr,
    "yahoo_us": fetch_yahoo_us,
    "upbit_crypto": fetch_upbit_crypto,
}


def _maybe_alert(name: str, old_price: float, new_price: float) -> bool:
    if not old_price:
        return False
    change_pct = (new_price - old_price) / old_price * 100
    if abs(change_pct) < ALERT_THRESHOLD_PCT:
        return False
    direction = "급등" if change_pct > 0 else "급락"
    safe_name = send_telegram.escape_html(name)
    text = (
        f"⚡️ <b>{safe_name}</b> {direction} 알림\n"
        f"{old_price:,.0f}원 → {new_price:,.0f}원 ({change_pct:+.1f}%)"
    )
    try:
        send_telegram.send_message(text)
    except Exception as e:
        print(f"!!! 알림 발송 실패 ({name}): {e}")
    return True


def main() -> None:
    db = get_db()
    codes: dict[str, dict] = {}
    for doc in db.collection("transactions").stream():
        t = doc.to_dict()
        codes.setdefault(t["code"], t)

    updated, skipped, alerted = 0, 0, 0
    for code, sample in codes.items():
        source = classify_price_source(sample)
        fetcher = FETCHERS.get(source)
        price = fetcher(code) if fetcher else None

        if price is None:
            skipped += 1
            continue

        prev_doc = db.collection("latest_prices").document(code).get()
        prev_price = prev_doc.to_dict().get("price_krw") if prev_doc.exists else None

        db.collection("latest_prices").document(code).set({
            "code": code,
            "name": sample["name"],
            "price_krw": price,
            "source": source,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        updated += 1

        if prev_price and _maybe_alert(sample["name"], prev_price, price):
            alerted += 1

    print(f"시세 갱신 완료: {updated}건 성공, {skipped}건 실패/미지원, {alerted}건 급등락 알림 (총 {len(codes)}종목)")


if __name__ == "__main__":
    main()
