// Caches the app shell (this is a single self-contained index.html, no other
// assets) so a cold load still works with no network at all. Network-first:
// always prefer the live page when reachable, fall back to the cached copy
// only when offline. That's why there's no cache-version bump here — staleness
// only ever matters in the fallback case, so there's nothing to go stale badly.
const CACHE = "grocery-shell";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return; // leave API calls and everything else alone
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        caches.open(CACHE).then((c) => c.put(event.request, res.clone()));
        return res;
      })
      .catch(() => caches.match(event.request))
  );
});
