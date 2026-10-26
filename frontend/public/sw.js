// Service worker de Zacilingua.
// Reglas para que nunca deje la app "atorada" en una versión vieja:
//  - La página (HTML) siempre se pide a la red primero; la copia guardada
//    solo se usa si no hay internet.
//  - Los archivos con nombre único de cada versión (/assets/...) sí se
//    guardan, porque nunca cambian.
//  - NUNCA toca peticiones a otros dominios (el backend en Render) ni a /api/.
//  - Al publicar una versión nueva, borra las copias de la anterior.

const VERSION = 'zacilingua-v3';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (evento) => {
    evento.waitUntil((async () => {
        const nombres = await caches.keys();
        await Promise.all(nombres.filter((n) => n !== VERSION).map((n) => caches.delete(n)));
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', (evento) => {
    const peticion = evento.request;
    const url = new URL(peticion.url);

    // Fuera: otros dominios (el backend), la API y todo lo que no sea GET.
    if (peticion.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

    // Página: red primero; si no hay internet, la última copia guardada.
    if (peticion.mode === 'navigate') {
        evento.respondWith((async () => {
            try {
                const respuesta = await fetch(peticion);
                const cache = await caches.open(VERSION);
                cache.put('/', respuesta.clone());
                return respuesta;
            } catch {
                return (await caches.match('/')) || Response.error();
            }
        })());
        return;
    }

    // Archivos versionados (/assets/...): de la caché si ya están.
    if (url.pathname.startsWith('/assets/')) {
        evento.respondWith((async () => {
            const guardada = await caches.match(peticion);
            if (guardada) return guardada;
            const respuesta = await fetch(peticion);
            if (respuesta.ok) (await caches.open(VERSION)).put(peticion, respuesta.clone());
            return respuesta;
        })());
    }
    // Todo lo demás pasa directo a la red, sin tocarlo.
});