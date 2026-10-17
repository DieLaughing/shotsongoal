// Caches the app shell so it opens instantly; data always comes from the network first. Photos and logos (/img/) are
// the other way round: the phone's copy first, kept in their own cache, so a face seen once never downloads again.
const CACHE = "sog-v5";
const IMAGES = "sog-img-v1";
const IMAGES_MAX = 600;   // about 2 MB of small photos; the oldest go first
const SHELL = ["/", "/offline.html", "/style.css", "/app.js", "/manifest.webmanifest", "/icons/icon.svg"];

// Cloudflare's codes for "can't reach the server behind the tunnel" (a real bug in the app is a plain 500).
const PI_DOWN = status => [502, 503, 504, 520, 521, 522, 523, 524, 530].includes(status);
const offline = () => caches.match("/offline.html").then(r => r || Response.error());

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE && k !== IMAGES).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/invite/") || url.pathname.startsWith("/cdn-cgi/")) return;
  if (url.pathname.startsWith("/img/")) {
    e.respondWith(caches.open(IMAGES).then(async c => {
      const hit = await c.match(e.request);
      if (hit) return hit;
      const res = await fetch(e.request);
      if (res.ok) {
        c.put(e.request, res.clone());
        c.keys().then(keys => keys.slice(0, Math.max(0, keys.length - IMAGES_MAX)).forEach(k => c.delete(k)));
      }
      return res;
    }));
    return;
  }
  // Opening the app while the Pi is down: Cloudflare answers 502/530 (or the phone has no network), so show
  // the cached offline page instead of Cloudflare's error page.
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request)
      .then(res => (PI_DOWN(res.status) ? offline() : res))
      .catch(offline));
    return;
  }
  e.respondWith(
    fetch(e.request)
      .then(res => {
        if (res.ok && !res.redirected) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, copy));
        }
        // Pi down: the cached copy (the offline page's icon, the app shell) beats Cloudflare's error.
        return PI_DOWN(res.status) ? caches.match(e.request).then(c => c || res) : res;
      })
      .catch(() => caches.match(e.request))
  );
});

// Web push: goal, final, puck-drop and trade alerts. Tapping one opens the game (or the Wire).
self.addEventListener("push", e => {
  let data = {};
  try { data = e.data.json(); } catch { data = { title: "Shots on Goal", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(data.title || "Shots on Goal", {
    body: data.body || "", tag: data.tag, data: { url: data.url || "/" },
    icon: "/icons/icon-192.png", badge: "/icons/icon-192.png",
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = e.notification.data?.url || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) {
      if (new URL(c.url).origin === location.origin) { c.navigate(url); return c.focus(); }
    }
    return self.clients.openWindow(url);
  }));
});
