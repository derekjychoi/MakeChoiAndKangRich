"""보유 종목을 자산군/시장으로 분류하는 결정적 규칙 모음.

투자 판단 로직이 아니라 이름/코드 패턴에 따른 기계적 분류다.
"""
from __future__ import annotations

# 이름 접두어로 국내 상장 ETF를 구분한다 (거래 데이터엔 ETF 여부 플래그가 없음).
KOREAN_ETF_PREFIXES = (
    "TIGER", "KODEX", "ACE", "SOL", "KBSTAR", "PLUS", "HANARO", "ARIRANG",
    "KINDEX", "KOSEF", "TIMEFOLIO", "WOORI", "히어로즈", "RISE", "마이다스",
)
# 해외 상장 ETF는 종목코드가 숫자가 아닌 티커라 이름만으로 구분이 안 되므로 별도 목록 사용.
US_ETF_TICKERS = {
    "TQQQ", "SPY", "QQQ", "VOO", "VTI", "SCHD", "SOXL", "SOXX", "IVV", "DIA", "ARKK", "SPXL",
}
CRYPTO_SECTORS = {"코인원", "빗썸", "업비트", "코인"}
CRYPTO_CODES = {"BTC", "ETH", "XRP", "SOL", "DOGE", "ADA", "AVAX", "TRX", "DOT", "MATIC"}


def classify_asset_class(holding: dict) -> str:
    """holdings/transaction 항목 하나를 4개 자산군 중 하나로 분류한다."""
    sector = holding.get("sector", "")
    name = holding.get("name", "")
    code = str(holding.get("code", ""))

    if sector in CRYPTO_SECTORS or code.upper() in CRYPTO_CODES:
        return "코인"
    if sector == "금":
        return "금"
    if code.isalpha() and code.upper() in US_ETF_TICKERS:
        return "주식(ETF)"
    if name.startswith(KOREAN_ETF_PREFIXES):
        return "주식(ETF)"
    return "주식(개별)"


def classify_price_source(holding: dict) -> str:
    """실시간 시세를 어디서 가져와야 하는지 결정한다: naver_kr | naver_gold | yahoo_us | upbit_crypto | unsupported."""
    sector = holding.get("sector", "")
    code = str(holding.get("code", ""))

    if sector in CRYPTO_SECTORS or code.upper() in CRYPTO_CODES:
        return "upbit_crypto"
    if sector == "금":
        return "naver_gold"  # KRX 금시장(국내 금, 원/g) - 네이버 marketindex API로 조회 가능
    if code.isalpha():
        return "yahoo_us"
    if any(ch.isdigit() for ch in code):
        # 국내 상장 코드는 기본 6자리 숫자지만, 최근 신규 상장 ETF는
        # "0035T0" 처럼 문자가 섞인 코드도 쓰인다 - 숫자가 하나라도 있으면 국내로 취급.
        return "naver_kr"
    return "unsupported"
