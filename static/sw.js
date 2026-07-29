// Service worker do Elite Hapkido — Check-in.
// Propositalmente simples: só faz cache de arquivos estáticos (CSS, ícones).
// Páginas (HTML) e ações de check-in NUNCA são cacheadas, para que o
// ranking e os status de aprovação sempre reflitam o servidor em tempo real.

const CACHE_NAME = "elite-hapkido-static-v1";
const STATIC_ASSETS = [
  "/static/css/style.css",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isStatic = url.pathname.startsWith("/static/");

  if (!isStatic || event.request.method !== "GET") {
    // Tudo que não é asset estático (páginas, check-in, login) vai direto à rede.
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
