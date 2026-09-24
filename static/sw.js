/* Service worker for FaceID Attendance.
 *
 * Deliberately conservative about what it keeps. This app holds students'
 * faces and their attendance, often on a shared staff phone, so the rules are:
 *
 *   - static assets (stylesheets, icons, scripts) are cached and served from
 *     the cache, because they are identical for everybody and never secret;
 *   - pages and /api/ responses are NEVER cached. A cached roster would leak
 *     one teacher's class to whoever opened the app next, and stale
 *     attendance shown as current is worse than no attendance at all;
 *   - when the network is gone and a page is asked for, an offline notice is
 *     shown instead, so the app explains itself rather than failing blank.
 *
 * BUILD is substituted by the server, so publishing a new version renames the
 * cache and the old one is deleted on activate. No stale shell after a deploy.
 */
const BUILD = "__BUILD__";
const CACHE = "faceid-shell-" + BUILD;

const SHELL = [
  "/static/app.css",
  "/static/icons.css",
  "/static/mobile.css",
  "/static/icons.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
  "/offline",
];

self.addEventListener("install", (event) => {
  // One bad URL must not fail the whole install, so each is added on its own.
  event.waitUntil(
    caches.open(CACHE).then((cache) =>
      Promise.all(SHELL.map((url) => cache.add(url).catch(() => null)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names.filter((n) => n.startsWith("faceid-shell-") && n !== CACHE)
             .map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

function isStaticAsset(url) {
  return url.origin === self.location.origin && url.pathname.startsWith("/static/");
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;          // never touch a POST
  const url = new URL(request.url);

  if (isStaticAsset(url)) {
    // Cache first: these change only when BUILD changes, which renames the cache.
    event.respondWith(
      caches.match(request).then((hit) =>
        hit || fetch(request).then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
      )
    );
    return;
  }

  if (request.mode === "navigate") {
    // Always from the network, so a teacher never sees yesterday's register.
    event.respondWith(
      fetch(request).catch(() =>
        caches.match("/offline").then((page) =>
          page || new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } })
        )
      )
    );
    return;
  }

  // Everything else -- /api/, photos, the Excel download -- goes straight to
  // the network and is never stored.
});
