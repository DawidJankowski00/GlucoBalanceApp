// Service worker: shows reminders that arrive as Web Push messages, even when the app is
// closed. It caches nothing, so the app always loads fresh from the server.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = { title: "GlucoBalanceApp", body: "", url: "/notifications" };
  try {
    data = { ...data, ...event.data.json() };
  } catch (_) {
    // A message without readable JSON still gets a generic notification.
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      data: { url: data.url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  // Only ever open a path on this site.
  const raw = (event.notification.data && event.notification.data.url) || "/notifications";
  const url = raw.startsWith("/") ? raw : "/notifications";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if ("focus" in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
