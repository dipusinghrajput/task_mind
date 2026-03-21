/* ─────────────────────────────────────────────
   AI Task Planner — Service Worker
   Handles: background push, offline cache, notification clicks
───────────────────────────────────────────── */

const CACHE_NAME = "aiplanner-v1";
const STATIC_ASSETS = [
  "/",
  "/static/css/main.css",
  "/static/js/app.js",
  "/static/manifest.json",
];

// ── INSTALL: cache static assets ──────────────
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// ── ACTIVATE: clear old caches ────────────────
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ── FETCH: network-first for API, cache for static ──
self.addEventListener("fetch", (e) => {
  if (e.request.url.includes("/api/")) {
    // API: always network
    e.respondWith(fetch(e.request).catch(() =>
      new Response(JSON.stringify({ error: "Offline" }), {
        headers: { "Content-Type": "application/json" },
      })
    ));
  } else {
    // Static: cache-first
    e.respondWith(
      caches.match(e.request).then((cached) => cached || fetch(e.request))
    );
  }
});

// ── PUSH: receive push from server and show notification ──
self.addEventListener("push", (e) => {
  let data = { title: "AI Task Planner", body: "You have a new update.", icon: "/static/icon.png" };
  try {
    data = e.data.json();
  } catch (_) {}

  e.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon || "/static/icon.png",
      badge: "/static/badge.png",
      tag: data.tag || "planner-notif",
      data: data.url || "/",
      vibrate: [200, 100, 200],
      actions: data.actions || [],
    })
  );
});

// ── NOTIFICATION CLICK: open/focus app ────────
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const targetUrl = e.notification.data || "/";
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && "focus" in client) {
          return client.focus();
        }
      }
      return clients.openWindow(targetUrl);
    })
  );
});

// ── BACKGROUND SYNC: poll for pending notifications ──
self.addEventListener("periodicsync", (e) => {
  if (e.tag === "check-notifications") {
    e.waitUntil(checkAndShowNotifications());
  }
});

// Also check every time SW activates (fallback for browsers without periodicSync)
async function checkAndShowNotifications() {
  try {
    const uid = await getStoredUserId();
    if (!uid) return;
    const res = await fetch(`/api/notifications/pending`, {
      headers: { "X-User-Id": uid },
    });
    if (!res.ok) return;
    const notifs = await res.json();
    for (const n of notifs) {
      await self.registration.showNotification(n.title, {
        body: n.message,
        icon: "/static/icon.png",
        tag: `notif-${n.id}`,
        data: "/",
        vibrate: [200, 100, 200],
      });
    }
  } catch (err) {
    console.error("[SW] checkAndShowNotifications error:", err);
  }
}

async function getStoredUserId() {
  try {
    const cache = await caches.open("aiplanner-user");
    const res = await cache.match("/user-id");
    if (res) return await res.text();
  } catch (_) {}
  return null;
}

// Message from main thread (e.g. store user_id for SW to use)
self.addEventListener("message", (e) => {
  if (e.data && e.data.type === "SET_USER_ID") {
    caches.open("aiplanner-user").then((cache) => {
      cache.put("/user-id", new Response(String(e.data.userId)));
    });
  }
  if (e.data && e.data.type === "CHECK_NOTIFICATIONS") {
    checkAndShowNotifications();
  }
});
