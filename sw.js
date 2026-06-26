const CACHE_NAME = "garage-log-v2";
const STATIC_FILES = [
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png",
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_FILES))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Two strategies depending on what's being requested:
//
// 1. The HTML page itself (navigation requests, and index.html directly):
//    NETWORK-FIRST. Always try to fetch the latest version first. Only fall
//    back to whatever's cached if the network request fails (actually
//    offline). This is the fix for "I updated GitHub but my phone still
//    shows the old version" -- the old cache-first approach served the
//    cached copy forever and never re-checked, even with a network
//    connection sitting right there.
//
// 2. Static assets (manifest, icons): CACHE-FIRST, same as before. These
//    almost never change, so serving them instantly from cache (with a
//    background refresh for next time) is the right tradeoff for offline
//    speed without needing the freshness guarantee the HTML needs.
self.addEventListener("fetch", (event) => {
  const isHTMLRequest =
    event.request.mode === "navigate" ||
    event.request.url.endsWith("/") ||
    event.request.url.endsWith("index.html");

  if (isHTMLRequest) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response && response.status === 200) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
          }
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (response && response.status === 200) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
        }
        return response;
      }).catch(() => cached);
    })
  );
});
