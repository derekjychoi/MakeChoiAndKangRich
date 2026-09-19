"""구글 시트에서 포트폴리오 데이터를 읽어 정제된 JSON 스냅샷으로 저장한다.

- 📊주식내역 탭: 거래 로그 -> transactions
- 📈주식현황상세 탭: 현재 보유 현황 -> holdings

두 탭 모두 valueRenderOption='UNFORMATTED_VALUE'로 읽어 콤마/₩ 기호가 섞이지
않은 원시 숫자를 얻는다. 날짜는 dateTimeRenderOption='FORMATTED_STRING'으로
읽어 사람이 읽을 수 있는 문자열을 유지한다.

실행:  python src/fetch_portfolio.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build

import config


# ---------------------------------------------------------------------------
# 📈주식현황상세 컬럼 인덱스 (UNFORMATTED_VALUE 기준, 0-based)
# 병합 셀 때문에 통화기호(₩/$)가 별도 컬럼(10, 13, 16)으로 분리되어 있어
# 아래 인덱스는 실제 원시 값을 스크립트로 출력해 재검증한 결과다.
#
#   [0] 시장   [1] 종목명   [2] 섹터   [3] 코드   [4] 보유량
#   [5] 매수평단가  [6] 매수총액($)  [7] 매수평단가(원)  [8] 매수총액(원)
#   [9] 평균환율  [10] '₩/$'  [11] 현재가(native)  [12] (현재가-매수평단가)
#   [13] '₩'  [14] 평가총액(native)  [15] 평가총액(원)
#   [16] '₩/$'  [17] 총수익(native)  [18] 총수익률(native fraction)
#   [19] 원화수익(원)  [20] 원화수익률(원화 기준 fraction)
#
# 주의: 총수익[17]/총수익률[18]은 네이티브 통화 기준이라 USD 종목에서 $ 값이
# 들어온다. 원화 기준 수익/수익률은 [19] 원화수익 / [20] 원화수익률을 써야
# KRW로 일관된다 (KRW 종목은 [17]==[19], [18]==[20] 이라 동일).
# ---------------------------------------------------------------------------
H_NAME = 1
H_SECTOR = 2
H_CODE = 3
H_QTY = 4
H_AVG_BUY_KRW = 7
H_TOTAL_BUY_KRW = 8
H_CUR_PRICE_NATIVE = 11
H_EVAL_TOTAL_KRW = 15
H_PROFIT_KRW = 19
H_PROFIT_FRACTION = 20

HOLDINGS_HEADER_ROWS = 2  # 앞 2행은 헤더/병합 셀


# 📊주식내역 컬럼 인덱스 (0-based)
#   [0] 구매일 [1] 증권사 [2] 매매구분 [3] 종목명 [4] 종목코드 [5] 시장구분
#   [6] 섹터 [7] 평단가 [8] 수량 [9] 세부분류 [10] 환율 [11] 환율보조
#   [12] 금액 [13] 실평단가 [14] 총액 [15] 총액(원) [16] 실현손익(원)
T_DATE = 0
T_BROKER = 1
T_TYPE = 2
T_NAME = 3
T_CODE = 4
T_MARKET = 5
T_SECTOR = 6
T_UNIT_PRICE = 7
T_QTY = 8
T_AMOUNT_KRW = 15
T_REALIZED_PNL = 16


def _sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        str(config.GOOGLE_SERVICE_ACCOUNT_PATH), scopes=config.GOOGLE_SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def _get_values(service, sheet_title: str, cell_range: str):
    return (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=config.SPREADSHEET_ID,
            range=f"'{sheet_title}'!{cell_range}",
            valueRenderOption="UNFORMATTED_VALUE",
            dateTimeRenderOption="FORMATTED_STRING",
        )
        .execute()
        .get("values", [])
    )


def _cell(row: list, idx: int):
    return row[idx] if idx < len(row) else None


def _to_float(value):
    """숫자/숫자문자열을 float로. 실패 시 None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    # 혹시 남아있을지 모르는 콤마/₩/$ 제거 후 시도
    s = str(value).replace(",", "").replace("₩", "").replace("$", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _clean_str(value):
    return str(value).strip() if value is not None else ""


def parse_transactions(rows: list) -> list:
    """헤더 1행을 제외한 거래 로그를 파싱한다."""
    out = []
    skipped = 0
    for row in rows[1:]:  # 첫 행은 헤더
        name = _clean_str(_cell(row, T_NAME))
        if not name:
            skipped += 1
            continue
        out.append(
            {
                "date": _clean_str(_cell(row, T_DATE)),
                "broker": _clean_str(_cell(row, T_BROKER)),
                "type": _clean_str(_cell(row, T_TYPE)),
                "name": name,
                "code": _clean_str(_cell(row, T_CODE)),
                "market": _clean_str(_cell(row, T_MARKET)),
                "sector": _clean_str(_cell(row, T_SECTOR)),
                "unit_price": _to_float(_cell(row, T_UNIT_PRICE)),
                "quantity": _to_float(_cell(row, T_QTY)),
                "amount": _to_float(_cell(row, T_AMOUNT_KRW)),
                "realized_pnl": _to_float(_cell(row, T_REALIZED_PNL)),
            }
        )
    if skipped:
        print(f"[transactions] 빈/비정상 행 {skipped}개 스킵", file=sys.stderr)
    return out


def parse_holdings(rows: list) -> list:
    """헤더 2행을 제외한 보유 현황을 파싱한다.

    현재가는 네이티브 통화(원/달러)로 저장돼 있으므로, KRW 일관성을 위해
    current_price_krw = 평가총액(원) / 보유량 으로 계산한다.
    (KRW 종목은 시트의 현재가와 정확히 일치, USD 종목은 올바른 원화 환산가가 됨)
    """
    out = []
    skipped = 0
    for row in rows[HOLDINGS_HEADER_ROWS:]:
        name = _clean_str(_cell(row, H_NAME))
        qty = _to_float(_cell(row, H_QTY))
        eval_total = _to_float(_cell(row, H_EVAL_TOTAL_KRW))
        # 종목명이 없거나 보유량이 없으면(현금/빈 행) 스킵
        if not name or qty is None or qty == 0:
            skipped += 1
            continue

        current_price_krw = round(eval_total / qty, 4) if eval_total is not None else None
        fraction = _to_float(_cell(row, H_PROFIT_FRACTION))
        profit_pct = round(fraction * 100, 4) if fraction is not None else None

        out.append(
            {
                "name": name,
                "sector": _clean_str(_cell(row, H_SECTOR)),
                "code": _clean_str(_cell(row, H_CODE)),
                "quantity": qty,
                "avg_buy_price_krw": _to_float(_cell(row, H_AVG_BUY_KRW)),
                "total_buy_krw": _to_float(_cell(row, H_TOTAL_BUY_KRW)),
                "current_price_krw": current_price_krw,
                "eval_total_krw": eval_total,
                "profit_krw": _to_float(_cell(row, H_PROFIT_KRW)),
                "profit_pct": profit_pct,
            }
        )
    if skipped:
        print(f"[holdings] 빈/현금/비정상 행 {skipped}개 스킵", file=sys.stderr)
    return out


def main() -> None:
    service = _sheets_service()

    tx_rows = _get_values(service, config.SHEET_TRANSACTIONS, "A1:Q")
    holdings_rows = _get_values(service, config.SHEET_HOLDINGS, "A1:W")

    transactions = parse_transactions(tx_rows)
    holdings = parse_holdings(holdings_rows)

    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "transactions": transactions,
        "holdings": holdings,
    }

    config.ensure_data_dir()
    with open(config.PORTFOLIO_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(
        f"저장 완료: {config.PORTFOLIO_SNAPSHOT_PATH} "
        f"(transactions={len(transactions)}, holdings={len(holdings)})"
    )


if __name__ == "__main__":
    main()
