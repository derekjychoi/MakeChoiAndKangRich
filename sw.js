// PWA 설치 가능하게 만드는 최소한의 서비스워커. 오프라인 캐싱은 하지 않는다
// (Firestore 실시간 데이터/로그인 팝업 위주 앱이라 캐싱이 오히려 혼란을 줄 수 있음) -
// 그냥 네트워크로 그대로 통과시키기만 한다.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
