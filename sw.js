// Caches the app shell (this is a single self-contained index.html, no other
// assets) so a cold load still works with no network at all. Races the network
// against a short timeout and serves the cached copy the instant that timeout
// wins — a dead/unreachable connection can take many seconds to actually fail,
// which made a plain network-first strategy feel like a freeze instead of an
// instant offline load. The network fetch keeps running in the background
// regardless, so the cache still gets refreshed when the network does answer.
// No cache-version bump scheme needed: the app's real data comes from
// localStorage/the sync API, not this shell, so a briefly-stale shell is a
// non-issue and staleness only ever shows up in the offline-fallback path.
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
    (async () => {
      const cache = await caches.open(CACHE);
      const network = fetch(event.request)
        .then((res) => { cache.put(SHELL, res.clone()); return res; })
        .catch(() => null);
      const timeout = new Promise((resolve) => setTimeout(() => resolve(null), 1500));

      const fast = await Promise.race([network, timeout]);
      if (fast) return fast;

      const cached = await cache.match(SHELL);
      if (cached) return cached; // network kept running in the background regardless

      return (await network) || Response.error(); // first-ever load, nothing cached yet — wait it out
    })()
  );
});
