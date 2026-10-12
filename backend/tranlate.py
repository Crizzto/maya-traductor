from flask import Flask, request, jsonify
from flask_cors import CORS
from asgiref.wsgi import WsgiToAsgi
import asyncio
import json
import logging
import os
import re
import requests
from pathlib import Path

app = Flask(__name__)
# Habilita CORS solo para /api/*, que es lo que va a llamar el frontend
# de React (corre en otro puerto durante desarrollo: localhost:3000 o
# parecido). El resto del sitio (la ruta "/" con Jinja) no lo necesita.
CORS(app, resources={r"/api/*": {"origins": "*"}})
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tranlate")

# Caché simple en memoria: evita volver a pegarle a Google por una frase
# que ya tradujiste antes (ayuda a no gastar tu cuota de peticiones y
# reduce las probabilidades de que te bloqueen por 429).
_cache_traducciones = {}

RUTA_DICCIONARIO = Path(__file__).parent / "diccionario.json"
RUTA_DICCIONARIO_COLONIAL = Path(__file__).parent / "diccionario_colonial.json"


def cargar_diccionario_local() -> dict:
    """
    Carga diccionario.json, que tiene esta forma:
    {
      "es-yua": { "palabra en español": "traducción en maya", ... },
      "yua-es": { "palabra en maya": "traducción en español", ... }
    }
    Se recarga en cada llamada (barato porque el archivo es pequeño),
    así puedes editar diccionario.json y ver los cambios sin reiniciar
    el servidor.
    """
    try:
        with open(RUTA_DICCIONARIO, encoding="utf-8") as f:
            datos = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("No se pudo leer diccionario.json: %s", e)
        return {}

    # Normaliza claves "es-yua" -> tupla ("es", "yua"), y todo a minúsculas
    resultado = {}
    for direccion, entradas in datos.items():
        src, dest = direccion.split("-")
        resultado[(src, dest)] = {
            k.strip().lower(): v for k, v in entradas.items()
        }
    return resultado


def _cargar_diccionario_colonial_una_vez() -> dict:
    """
    Carga diccionario_colonial.json (el glosario sacado del PDF de
    vocabularios coloniales). A diferencia de diccionario.json, este NO
    se recarga en cada petición: es grande (~1.6 MB, ~39 mil entradas) y
    no lo vas a estar editando a mano constantemente, así que se carga
    una sola vez cuando arranca el servidor.
    """
    try:
        with open(RUTA_DICCIONARIO_COLONIAL, encoding="utf-8") as f:
            datos = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("No se pudo leer diccionario_colonial.json: %s", e)
        return {}

    resultado = {}
    for direccion, entradas in datos.items():
        src, dest = direccion.split("-")
        resultado[(src, dest)] = {
            k.strip().lower(): v for k, v in entradas.items()
        }
    return resultado


DICCIONARIO_COLONIAL = _cargar_diccionario_colonial_una_vez()


def normalizar(texto: str) -> str:
    """Unifica los distintos caracteres de apóstrofe/saltillo a uno solo."""
    return re.sub(r"['‘’ʻ]", "'", texto)


# --- Azure Translator (motor principal) ---
# Lee la clave y región desde variables de entorno; nunca las escribas
# directo en el código. En local puedes definirlas antes de correr la
# app, y en Render se ponen en Environment del servicio del backend.
AZURE_KEY = os.environ.get("AZURE_TRANSLATOR_KEY", "")
AZURE_REGION = os.environ.get("AZURE_TRANSLATOR_REGION", "")
AZURE_ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"


def azure_translate(texto: str, src: str, dest: str) -> str:
    """
    Traduce usando Azure Translator (API oficial, autenticada con clave).
    A diferencia del scraping de Google, esto SÍ funciona bien desde
    servidores en la nube como Render, porque es tráfico autorizado,
    no scraping.
    """
    if not AZURE_KEY or not AZURE_REGION:
        raise RuntimeError(
            "Faltan las variables de entorno AZURE_TRANSLATOR_KEY / "
            "AZURE_TRANSLATOR_REGION."
        )

    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-Type": "application/json",
    }
    params = {"api-version": "3.0", "from": src, "to": dest}
    cuerpo = [{"Text": texto}]

    resp = requests.post(
        AZURE_ENDPOINT, params=params, headers=headers, json=cuerpo, timeout=10
    )
    resp.raise_for_status()
    datos = resp.json()
    return datos[0]["translations"][0]["text"]


# --- Google directo (respaldo opcional, último recurso) ---
# Se deja como último intento por si Azure falla por cualquier motivo,
# pero ten presente que desde un servidor en la nube Google suele
# bloquearlo con 429 — no cuentes con que esto funcione en producción.
HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Referer": "https://translate.google.com/",
}
_sesion = requests.Session()
_sesion.headers.update(HEADERS_NAVEGADOR)


def google_translate_directo(texto: str, src: str, dest: str) -> str:
    url = "https://translate.googleapis.com/translate_a/single"
    params = {"client": "gtx", "sl": src, "tl": dest, "dt": "t", "q": texto}
    resp = _sesion.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return "".join(fragmento[0] for fragmento in data[0] if fragmento[0])


async def traducir_con_respaldo(texto: str, src: str, dest: str) -> str:
    """
    Intenta traducir en este orden:
    1. Diccionario local (más confiable para yua).
    2. Caché en memoria (evita repetir peticiones idénticas).
    3. Google Translate directo, con reintentos y espera creciente si
       Google responde 429 (límite de peticiones).
    Si todo falla, regresa un mensaje claro en vez de tronar.
    """
    clave = normalizar(texto).strip().lower()

    # 1) Diccionario local tuyo, verificado (se recarga cada vez para
    # tomar ediciones nuevas al vuelo)
    diccionario = cargar_diccionario_local()
    entrada_local = diccionario.get((src, dest), {})
    if clave in entrada_local:
        logger.info("[FUENTE: diccionario.json] %r -> %r", clave, entrada_local[clave])
        return entrada_local[clave]

    # 2) Diccionario colonial (glosario sacado del PDF de vocabularios
    # históricos). Se avisa la fuente porque usa ortografía antigua del
    # maya, distinta a la moderna.
    entrada_colonial = DICCIONARIO_COLONIAL.get((src, dest), {})
    if clave in entrada_colonial:
        logger.info("[FUENTE: diccionario_colonial.json] %r -> %r", clave, entrada_colonial[clave])
        return f"{entrada_colonial[clave]} (fuente histórica, ortografía colonial)"

    # 3) Caché en memoria
    clave_cache = (src, dest, clave)
    if clave_cache in _cache_traducciones:
        logger.info("[FUENTE: caché en memoria] %r", clave)
        return _cache_traducciones[clave_cache]

    texto_para_traducir = normalizar(texto)

    # 4) Azure Translator (motor principal en producción)
    try:
        resultado = await asyncio.to_thread(
            azure_translate, texto_para_traducir, src, dest
        )
        if resultado:
            logger.info("[FUENTE: Azure Translator] %r -> %r", texto_para_traducir, resultado)
            _cache_traducciones[clave_cache] = resultado
            return resultado
    except Exception as e:
        logger.warning("Azure Translator falló: %s", e)

    # 5) Google directo, solo como último recurso (puede fallar en la nube)
    try:
        resultado = await asyncio.to_thread(
            google_translate_directo, texto_para_traducir, src, dest
        )
        if resultado:
            logger.info("[FUENTE: Google (respaldo)] %r -> %r", texto_para_traducir, resultado)
            _cache_traducciones[clave_cache] = resultado
            return resultado
    except Exception as e:
        logger.warning("Google Translate (respaldo) falló: %s", e)

    return "No se pudo traducir en este momento. Intenta de nuevo más tarde."


def _resolver_direccion(valor: str):
    """
    Acepta tanto el formato que ya usaba el index.html viejo ('es-yua',
    'yua-es') como el que manda el frontend nuevo de React ('spanish',
    'maya' -> se interpreta junto con el idioma de destino implícito).
    Devuelve (src, dest) o (None, None) si no reconoce el valor.
    """
    mapa = {
        "es-yua": ("es", "yua"),
        "yua-es": ("yua", "es"),
        "spanish-maya": ("es", "yua"),
        "maya-spanish": ("yua", "es"),
    }
    return mapa.get(valor, (None, None))


@app.route("/api/traducir", methods=["POST"])
async def api_traducir():
    """
    Endpoint JSON para el frontend de React (Lovable).
    Espera: { "texto": "...", "direccion": "maya-spanish" | "spanish-maya" }
    Responde: { "resultado": "..." } o { "error": "..." } con código 400.
    """
    datos = request.get_json(silent=True) or {}
    texto = (datos.get("texto") or "").strip()
    direccion = datos.get("direccion", "")

    src, dest = _resolver_direccion(direccion)
    if src is None:
        return jsonify(error="Dirección de traducción inválida."), 400
    if not texto:
        return jsonify(error="Escribe algo para traducir."), 400

    resultado = await traducir_con_respaldo(texto, src, dest)
    return jsonify(resultado=resultado)


@app.route("/", methods=["GET"])
def estado():
    """
    La interfaz de verdad ahora es la app de React (frontend/), que corre
    por separado. Esta ruta solo sirve para confirmar que el backend está
    vivo si entras a su URL directamente.
    """
    return jsonify(
        estado="ok",
        mensaje="Backend del Traductor Maya funcionando. Usa /api/traducir (POST).",
    )


app = WsgiToAsgi(app)

if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 en vez de 127.0.0.1: así otros dispositivos en tu misma red
    # (como tu celular) también pueden conectarse, no solo esta compu.
    uvicorn.run("tranlate:app", host="0.0.0.0", port=8001, reload=True)