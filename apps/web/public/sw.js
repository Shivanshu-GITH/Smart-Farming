// SmartFarm service worker — offline app shell.
// Strategy: network-first for navigations (falls back to a cached shell when
// offline), stale-while-revalidate for same-origin static assets. API calls and
// map tiles are never cached here — they need live data / their own caching.
const CACHE = "smartfarm-v1";
const SHELL = ["/"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return; // never touch POST/PUT (auth, API)

  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;

  // App navigations: network-first, fall back to cached shell offline.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          caches.open(CACHE).then((c) => c.put("/", res.clone()));
          return res;
        })
        .catch(() => caches.match("/"))
    );
    return;
  }

  // Same-origin static assets: stale-while-revalidate.
  if (sameOrigin) {
    event.respondWith(
      caches.match(req).then((cached) => {
        const fetched = fetch(req)
          .then((res) => {
            if (res.ok) caches.open(CACHE).then((c) => c.put(req, res.clone()));
            return res;
          })
          .catch(() => cached);
        return cached || fetched;
      })
    );
  }
});
