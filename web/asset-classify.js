// src/asset_classify.py 와 동일한 규칙의 JS 포팅본 (홀딩 실시간 계산용).

const KOREAN_ETF_PREFIXES = [
  "TIGER", "KODEX", "ACE", "SOL", "KBSTAR", "PLUS", "HANARO", "ARIRANG",
  "KINDEX", "KOSEF", "TIMEFOLIO", "WOORI", "히어로즈", "RISE", "마이다스",
];
const US_ETF_TICKERS = new Set([
  "TQQQ", "SPY", "QQQ", "VOO", "VTI", "SCHD", "SOXL", "SOXX", "IVV", "DIA", "ARKK", "SPXL",
]);
const CRYPTO_SECTORS = new Set(["코인원", "빗썸", "업비트", "코인"]);
const CRYPTO_CODES = new Set(["BTC", "ETH", "XRP", "SOL", "DOGE", "ADA", "AVAX", "TRX", "DOT", "MATIC"]);

export function classifyAssetClass(h) {
  const sector = h.sector || "";
  const name = h.name || "";
  const code = String(h.code || "");

  if (CRYPTO_SECTORS.has(sector) || CRYPTO_CODES.has(code.toUpperCase())) return "코인";
  if (sector === "금") return "금";
  if (/^[A-Za-z]+$/.test(code) && US_ETF_TICKERS.has(code.toUpperCase())) return "주식(ETF)";
  if (KOREAN_ETF_PREFIXES.some((p) => name.startsWith(p))) return "주식(ETF)";
  return "주식(개별)";
}
