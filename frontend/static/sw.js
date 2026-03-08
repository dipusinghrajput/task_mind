/* TaskMind Service Worker — handles push notifications + offline caching */
const CACHE = 'taskmind-v1';
const PRECACHE = ['/', '/static/css/main.css', '/static/js/app.js'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) return; // never cache API
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});

/* ── Push notification handler ─────────────────────────────────────────── */
self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : {};
  const title = data.title || 'TaskMind Reminder';
  const opts = {
    body: data.body || 'You have an upcoming task.',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/badge-72.png',
    tag: data.tag || 'taskmind',
    data: data,
    actions: [
      { action: 'start', title: '▶ Start Now' },
      { action: 'snooze', title: '⏰ +15 min' }
    ],
    requireInteraction: true,
    vibrate: [200, 100, 200]
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'snooze') {
    // Re-show after 15 minutes
    const data = e.notification.data || {};
    setTimeout(() => {
      self.registration.showNotification('⏰ Snoozed Reminder — TaskMind', {
        body: e.notification.body,
        icon: '/static/icons/icon-192.png',
        tag: 'taskmind-snooze'
      });
    }, 15 * 60 * 1000);
    return;
  }
  e.waitUntil(
    clients.matchAll({ type: 'window' }).then(list => {
      for (const client of list) {
        if (client.url.includes(self.location.origin)) {
          client.focus();
          return;
        }
      }
      return clients.openWindow('/');
    })
  );
});

/* ── Scheduled notification alarm (postMessage from app) ───────────────── */
self.addEventListener('message', e => {
  if (e.data?.type === 'SCHEDULE_NOTIF') {
    const { delay, title, body, tag } = e.data;
    setTimeout(() => {
      self.registration.showNotification(title, {
        body,
        icon: '/static/icons/icon-192.png',
        badge: '/static/icons/badge-72.png',
        tag: tag || 'taskmind',
        vibrate: [200, 100, 200],
        requireInteraction: false,
        actions: [
          { action: 'start', title: '▶ Start Now' },
          { action: 'snooze', title: '⏰ +15 min' }
        ]
      });
    }, delay);
  }
});
