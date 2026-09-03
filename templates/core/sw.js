{% load static %}/* Service worker. Randat prin Django ca sa poata folosi URL-urile statice
 * cu hash generate de collectstatic. */

const VERSION = "{{ cache_version }}";
const CACHE = `asistent-${VERSION}`;
const OFFLINE_URL = "/offline/";

/* Doar resurse publice, fara date personale. */
const PRECACHE = [
  OFFLINE_URL,
  "{% static 'css/app.css' %}",
  "{% static 'css/tokens.css' %}",
  "{% static 'css/base.css' %}",
  "{% static 'css/components/card.css' %}",
  "{% static 'css/components/nav.css' %}",
  "{% static 'css/components/controls.css' %}",
  "{% static 'css/components/features.css' %}",
  "{% static 'js/main.js' %}",
  "{% static 'js/vendor/htmx-2.0.4.min.js' %}",
  "{% static 'img/icons/icon-192.png' %}",
  "{% static 'img/icons/icon-512.png' %}",
];

/* Rute care nu se pun niciodata in cache: contin date personale sau fisiere
 * incarcate de utilizator. Un cache al acestora ar fi o scurgere de date. */
const NEVER_CACHE = ["/media/", "/documente/", "/rezumat/audio/", "/asistent/", "/admin/"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (NEVER_CACHE.some((prefix) => url.pathname.startsWith(prefix))) return;

  /* Navigari: intai reteaua, apoi cache, apoi pagina offline. */
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request).then((cached) => cached || caches.match(OFFLINE_URL)))
    );
    return;
  }

  /* Fisiere statice: intai reteaua, ca actualizarile de interfata si clickurile
   * sa nu ramana blocate intr-o versiune veche. Cache-ul este doar fallback. */
  if (url.pathname.startsWith("{% get_static_prefix %}")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request))
    );
  }
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {};
  }
  const title = payload.title || "Voice Task";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: payload.body || "",
      icon: "{% static 'img/icons/icon-192.png' %}",
      badge: "{% static 'img/icons/icon-192.png' %}",
      /* Aceeasi cheie de deduplicare ca pe server: sistemul de operare
         suprascrie notificarea in loc sa afiseze un duplicat. */
      tag: payload.dedup_key || "asistent",
      renotify: false,
      data: { url: payload.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      const existing = clients.find((client) => client.url.includes(self.location.origin));
      if (existing) {
        existing.navigate(target);
        return existing.focus();
      }
      return self.clients.openWindow(target);
    })
  );
});
