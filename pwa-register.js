// 모든 페이지에서 공통으로 import해서 서비스워커를 등록한다.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch((err) => {
      console.warn("서비스워커 등록 실패:", err);
    });
  });
}
