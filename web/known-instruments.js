// add-transaction.html / journal.html이 거래 내역을 어차피 전체 조회할 때,
// 그 결과로 settings/known_instruments 캐시(종목 목록 + 현재 보유 여부)를
// 같이 갱신해준다. refresh_live_prices.py가 5분마다 이 캐시만 읽고, "held"인
// 종목만 시세를 조회/알림 대상으로 삼는다 (전량매도한 종목은 더 이상 조회 안 함).
import { doc, setDoc } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";
import { computeHoldings } from "./holdings-calc.js";

export async function syncKnownInstruments(db, allTransactions) {
  const seen = new Map(); // code -> {name, sector}
  allTransactions.forEach((t) => {
    seen.set(t.code, { name: t.name, sector: t.sector });
  });
  const heldCodes = new Set(computeHoldings(allTransactions).map((h) => h.code));

  const map = {};
  seen.forEach((info, code) => {
    map[code] = { name: info.name, sector: info.sector, held: heldCodes.has(code) };
  });

  try {
    await setDoc(doc(db, "settings", "known_instruments"), map);
  } catch (err) {
    console.warn("known_instruments 동기화 실패:", err);
  }
}
