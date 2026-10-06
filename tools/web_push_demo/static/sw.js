self.addEventListener("push", event => {
  let payload = {title: "إشعار جديد", body: "لديك رسالة جديدة."};
  try {
    if (event.data) payload = {...payload, ...event.data.json()};
  } catch (_) {
    if (event.data) payload.body = event.data.text();
  }
  event.waitUntil(self.registration.showNotification(payload.title, {
    body: payload.body,
    tag: payload.tag || "personnel-notification",
    data: {url: payload.url || "/"},
    dir: "rtl",
    lang: "ar",
    requireInteraction: true,
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil(clients.matchAll({type: "window", includeUncontrolled: true}).then(windows => {
    const existing = windows.find(client => "focus" in client);
    return existing ? existing.focus() : clients.openWindow(event.notification.data?.url || "/");
  }));
});
