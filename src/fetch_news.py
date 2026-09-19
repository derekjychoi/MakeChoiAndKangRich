"""보유 종목별 최신 뉴스를 네이버 뉴스 검색 API로 수집한다.

입력: data/portfolio_snapshot.json 의 holdings
출력: data/news_snapshot.json  -> { "종목명": [ {title, link, description, pub_date}, ... ] }

- 종목명 그대로 검색 (sort=date, 상위 5개)
- title/description 의 HTML 태그/엔티티 제거
- 종목별 호출 사이 짧은 지연으로 레이트리밋 방지
- 개별 종목 실패는 빈 리스트로 두고 계속 진행, 실패 요약은 stderr 출력

실행:  python src/fetch_news.py
"""
from __future__ import annotations

import html
import json
import re
import sys
import time

import requests

import config

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
DISPLAY = 5
REQUEST_DELAY_SEC = 0.3
TIMEOUT_SEC = 10

_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(raw: str) -> str:
    """<b> 등 HTML 태그 제거 후 &quot; 같은 엔티티를 언이스케이프한다."""
    if not raw:
        return ""
    no_tags = _TAG_RE.sub("", raw)
    return html.unescape(no_tags).strip()


def fetch_news_for(name: str, headers: dict) -> list:
    params = {"query": name, "display": DISPLAY, "sort": "date"}
    resp = requests.get(
        NAVER_NEWS_URL, headers=headers, params=params, timeout=TIMEOUT_SEC
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [
        {
            "title": clean_text(it.get("title", "")),
            "link": it.get("originallink") or it.get("link", ""),
            "description": clean_text(it.get("description", "")),
            "pub_date": it.get("pubDate", ""),
        }
        for it in items
    ]


def load_holding_names() -> list:
    with open(config.PORTFOLIO_SNAPSHOT_PATH, encoding="utf-8") as f:
        snapshot = json.load(f)
    names = []
    seen = set()
    for h in snapshot.get("holdings", []):
        name = h.get("name", "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def main() -> None:
    if not config.NAVER_CLIENT_ID or not config.NAVER_CLIENT_SECRET:
        print("네이버 API 자격증명이 없습니다 (secrets/naver-api.env 확인)", file=sys.stderr)
        sys.exit(1)

    headers = {
        "X-Naver-Client-Id": config.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": config.NAVER_CLIENT_SECRET,
    }

    names = load_holding_names()
    result: dict[str, list] = {}
    failures: list[str] = []

    for i, name in enumerate(names):
        try:
            result[name] = fetch_news_for(name, headers)
        except Exception as exc:  # noqa: BLE001 - 개별 실패는 죽이지 않음
            result[name] = []
            failures.append(f"{name}: {exc}")
        if i < len(names) - 1:
            time.sleep(REQUEST_DELAY_SEC)

    config.ensure_data_dir()
    with open(config.NEWS_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    ok = sum(1 for v in result.values() if v)
    empty = sum(1 for v in result.values() if not v)
    print(
        f"저장 완료: {config.NEWS_SNAPSHOT_PATH} "
        f"(종목 {len(names)}개, 뉴스있음 {ok}, 빈결과/실패 {empty})"
    )
    if failures:
        print("실패 종목:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)


if __name__ == "__main__":
    main()
