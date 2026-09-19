"""특정 날짜(월말) 기준 과거 종가를 소스별로 조회한다.

launchd가 몇 분마다 돌리는 refresh_live_prices.py(latest_prices 컬렉션 = "지금 이 순간"
시세)와는 목적이 다르다. 월간 리포트는 그 달 말 시점으로 영구히 고정돼야 하므로
(몇 번을 다시 실행해도 같은 달이면 항상 같은 값이 나와야 함) 항상 이 모듈로 그 날짜의
과거 시세를 다시 조회해서 쓴다.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import requests

from asset_classify import classify_price_source

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _naver_kr_close(code: str, as_of: date) -> float | None:
    start = as_of - timedelta(days=10)
    try:
        r = requests.get(
            "https://api.finance.naver.com/siseJson.naver",
            params={
                "symbol": code, "requestType": 1,
                "startTime": start.strftime("%Y%m%d"),
                "endTime": as_of.strftime("%Y%m%d"),
                "timeframe": "day",
            },
            headers=HEADERS, timeout=8,
        )
        r.raise_for_status()
        # 응답이 진짜 JSON이 아니라 JS 배열 리터럴이라 정규식으로 행을 직접 뽑는다.
        rows = re.findall(
            r'\["(\d{8})",\s*([\-\d.]+),\s*([\-\d.]+),\s*([\-\d.]+),\s*([\-\d.]+),',
            r.text,
        )
        if not rows:
            return None
        return float(rows[-1][4])  # 마지막 행의 종가
    except Exception:
        return None


def _upbit_krw_close(code: str, as_of: date) -> float | None:
    try:
        to_param = (as_of + timedelta(days=1)).strftime("%Y-%m-%d") + " 00:00:00"
        r = requests.get(
            "https://api.upbit.com/v1/candles/days",
            params={"market": f"KRW-{code.upper()}", "to": to_param, "count": 1},
            headers=HEADERS, timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        return float(data[0]["trade_price"]) if data else None
    except Exception:
        return None


def _yahoo_close(ticker: str, as_of: date) -> float | None:
    try:
        start = as_of - timedelta(days=7)
        end = as_of + timedelta(days=1)
        period1 = int(datetime.combine(start, datetime.min.time()).timestamp())
        period2 = int(datetime.combine(end, datetime.min.time()).timestamp())
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"period1": period1, "period2": period2, "interval": "1d"},
            headers=HEADERS, timeout=8,
        )
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        return float(closes[-1]) if closes else None
    except Exception:
        return None


def _yahoo_us_krw_close(ticker: str, as_of: date) -> float | None:
    price_usd = _yahoo_close(ticker, as_of)
    rate = _yahoo_close("KRW=X", as_of)
    if price_usd is None or rate is None:
        return None
    return price_usd * rate


_FETCHERS = {
    "naver_kr": _naver_kr_close,
    "yahoo_us": _yahoo_us_krw_close,
    "upbit_crypto": _upbit_krw_close,
}


def fetch_historical_price_map(transactions: list[dict], as_of: date) -> dict[str, dict]:
    """transactions에 등장하는 종목들의 as_of 시점 종가를 조회한다.
    price_map: {code: {"price_krw": float}}. 조회 실패/미지원 종목은 결과에서 빠진다
    (holdings_calc.apply_prices가 평단가로 대체 처리).
    """
    codes: dict[str, dict] = {}
    for t in transactions:
        codes.setdefault(t["code"], t)

    price_map: dict[str, dict] = {}
    for code, sample in codes.items():
        source = classify_price_source(sample)
        fetcher = _FETCHERS.get(source)
        price = fetcher(code, as_of) if fetcher else None
        if price is not None:
            price_map[code] = {"price_krw": price}
    return price_map
