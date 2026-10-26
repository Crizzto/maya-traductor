"""
Protección básica del backend contra abuso.

Limita cuántas peticiones puede hacer cada IP a cada endpoint en una
ventana de tiempo. Si alguien encuentra la URL de tu backend y la usa
con un script, se topa con estos límites en vez de gastarse tu cuota de
Azure y Gemini.

Es un limitador en memoria: funciona bien con un solo proceso (como en
local o en el plan gratuito de Render). Se reinicia si el servidor se
reinicia, lo cual está bien para este propósito.
"""

import logging
import os
import threading
import time
from collections import defaultdict, deque

from flask import jsonify, request

logger = logging.getLogger("tranlate")

# (máximo de peticiones, ventana en segundos) por endpoint y por IP.
# Pensados para que una persona usando la app normalmente nunca los note.
LIMITES = {
    "/api/traducir": [(30, 60), (600, 86400)],
    "/api/chat": [(20, 60), (300, 86400)],
    "/api/agente": [(8, 60), (100, 86400)],
    "/api/voz/token": [(10, 3600), (30, 86400)],
    "/api/sugerencias": [(10, 3600)],
}

# En Render (o detrás de cualquier proxy) la IP real del usuario viene en
# una cabecera; en local se usa la IP de la conexión directamente. Render
# define la variable RENDER automáticamente.
CONFIAR_EN_PROXY = bool(os.environ.get("RENDER") or os.environ.get("CONFIAR_PROXY"))

_registros: dict[tuple[str, str, int], deque] = defaultdict(deque)
_candado = threading.Lock()
_ultima_limpieza = time.monotonic()


def ip_cliente() -> str:
    if CONFIAR_EN_PROXY:
        directa = request.headers.get("CF-Connecting-IP") or request.headers.get("True-Client-IP")
        if directa:
            return directa.strip()
        reenviada = request.headers.get("X-Forwarded-For", "")
        if reenviada:
            return reenviada.split(",")[0].strip()
    return request.remote_addr or "desconocida"


def _limpiar_viejos(ahora: float) -> None:
    """Borra registros vencidos de vez en cuando para que no crezca la memoria."""
    global _ultima_limpieza
    if ahora - _ultima_limpieza < 600:
        return
    _ultima_limpieza = ahora
    for clave in list(_registros):
        ventana = clave[2]
        marcas = _registros[clave]
        while marcas and ahora - marcas[0] > ventana:
            marcas.popleft()
        if not marcas:
            del _registros[clave]


def _texto_espera(segundos: float) -> str:
    if segundos < 90:
        return f"{max(1, int(segundos))} segundos"
    if segundos < 5400:
        return f"{int(segundos // 60)} minutos"
    return f"{int(segundos // 3600)} horas"


def revisar_limite():
    """Hook before_request: responde 429 si la IP ya pasó algún límite."""
    if request.method == "OPTIONS":  # las verificaciones CORS del navegador no cuentan
        return None
    limites = LIMITES.get(request.path)
    if not limites:
        return None

    ip = ip_cliente()
    ahora = time.monotonic()
    with _candado:
        _limpiar_viejos(ahora)
        for maximo, ventana in limites:
            marcas = _registros[(ip, request.path, ventana)]
            while marcas and ahora - marcas[0] > ventana:
                marcas.popleft()
            if len(marcas) >= maximo:
                espera = ventana - (ahora - marcas[0])
                logger.warning("[LÍMITE] %s superó %s peticiones/%ss en %s", ip, maximo, ventana, request.path)
                respuesta = jsonify(error=f"Demasiadas solicitudes seguidas. Intenta de nuevo en {_texto_espera(espera)}.")
                respuesta.status_code = 429
                respuesta.headers["Retry-After"] = str(int(espera) + 1)
                return respuesta
        for maximo, ventana in limites:
            _registros[(ip, request.path, ventana)].append(ahora)
    return None


def instalar(app) -> None:
    app.before_request(revisar_limite)
