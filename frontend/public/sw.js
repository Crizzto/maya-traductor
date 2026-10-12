// Service worker mínimo para Zacilingua.
// No intenta cachear todo el sitio (sería frágil con un bundler como Vite,
// cuyos nombres de archivo cambian en cada build). Solo guarda el "cascarón"
// de la app para que abra algo aunque no haya red, y deja que el navegador
// maneje el resto normalmente.

const CACHE_NOMBRE = "zacilingua-v1";
const RUTAS_BASE = ["/", "/manifest.json", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (evento) => {
    evento.waitUntil(
        caches.open(CACHE_NOMBRE).then((cache) => cache.addAll(RUTAS_BASE))
    );
    self.skipWaiting();
});

self.addEventListener("activate", (evento) => {
    evento.waitUntil(
        caches.keys().then((nombres) =>
            Promise.all(
                nombres
                    .filter((nombre) => nombre !== CACHE_NOMBRE)
                    .map((nombre) => caches.delete(nombre))
            )
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", (evento) => {
    // Nunca intercepta llamadas a la API (siempre deben ir a la red real).
    if (evento.request.url.includes("/api/")) return;

    evento.respondWith(
        caches.match(evento.request).then((respuestaCache) => {
            return (
                respuestaCache ||
                fetch(evento.request).catch(() => caches.match("/"))
            );
        })
    );
});