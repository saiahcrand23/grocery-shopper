// Caches the app shell (this is a single self-contained index.html, no other
// assets) so a cold load still works with no network at all. Network-first:
// always prefer the live page when reachable, fall back to the cached copy
// only when offline. That's why there's no cache-version bump here — staleness
// only ever matters in the fallback case, so there's nothing to go stale badly.
const CACHE = "grocery-shell";
// Fixed cache key, deliberately decoupled from whatever exact URL the page
// happens to be opened at (with/without a trailing slash, with/without
// "index.html", ...) — it's the same single-file app either way, so both
// writing and reading the cache always go through this one key.
const SHELL = "shell";

self.addEventListener("install", (event) => {
  // Precache the shell right away — otherwise nothing's cached until a
  // *second* navigation, since the very first load that registers this
  // worker already happened before it existed to intercept anything.
  event.waitUntil(
    fetch(self.registration.scope)
      .then((res) => caches.open(CACHE).then((c) => c.put(SHELL, res)))
      .catch(() => {})
  );
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
        caches.open(CACHE).then((c) => c.put(SHELL, res.clone()));
        return res;
      })
      .catch(() => caches.match(SHELL))
  );
});
