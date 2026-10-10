from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from asgiref.wsgi import WsgiToAsgi
import asyncio
import json
import logging
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


HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Referer": "https://translate.google.com/",
}

# Sesión reutilizada entre peticiones: mantiene cookies como haría un
# navegador real, en vez de abrir una conexión nueva y "anónima" cada vez.
_sesion = requests.Session()
_sesion.headers.update(HEADERS_NAVEGADOR)


def google_translate_directo(texto: str, src: str, dest: str) -> str:
    """
    Le pega directo al endpoint público de Google Translate (el mismo que
    usan googletrans y otras librerías por debajo), sin pasar por la lista
    de idiomas restringida que trae deep-translator's GoogleTranslator.
    Esto es necesario porque 'yua' no siempre aparece en esa lista fija,
    aunque el servicio de Google sí lo traduce.
    """
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": src,
        "tl": dest,
        "dt": "t",
        "q": texto,
    }
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
        return entrada_local[clave]

    # 2) Diccionario colonial (glosario sacado del PDF de vocabularios
    # históricos). Se avisa la fuente porque usa ortografía antigua del
    # maya, distinta a la moderna.
    entrada_colonial = DICCIONARIO_COLONIAL.get((src, dest), {})
    if clave in entrada_colonial:
        return f"{entrada_colonial[clave]} (fuente histórica, ortografía colonial)"

    # 3) Caché en memoria
    clave_cache = (src, dest, clave)
    if clave_cache in _cache_traducciones:
        return _cache_traducciones[clave_cache]

    texto_para_traducir = normalizar(texto)

    # 4) Google Translate directo. Un solo intento: reintentar de inmediato
    # varias veces solo empeora el límite de peticiones cuando ya nos
    # topamos con un 429.
    try:
        resultado = await asyncio.to_thread(
            google_translate_directo, texto_para_traducir, src, dest
        )
        if resultado:
            _cache_traducciones[clave_cache] = resultado
            return resultado
    except requests.exceptions.HTTPError as e:
        logger.warning("Google Translate falló: %s", e)
        if getattr(e.response, "status_code", None) == 429:
            return (
                "Google está limitando las peticiones ahora mismo (error 429). "
                "Espera unos minutos sin volver a intentar y prueba de nuevo."
            )
    except Exception as e:
        logger.warning("Google Translate falló: %s", e)

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


@app.route("/", methods=["GET", "POST"])
async def index():
    resultado = ""
    texto_original = ""
    seleccion = "es-yua"

    if request.method == "POST":
        texto_original = request.form["texto"]
        seleccion = request.form["idioma"]

        if seleccion == "es-yua":
            src, dest = "es", "yua"
        elif seleccion == "yua-es":
            src, dest = "yua", "es"
        else:
            src = dest = None

        if src is None:
            resultado = "Selección de idioma inválida."
        elif not texto_original.strip():
            resultado = "Escribe algo para traducir."
        else:
            resultado = await traducir_con_respaldo(texto_original, src, dest)

    return render_template(
        "index.html", resultado=resultado, texto=texto_original, seleccion=seleccion
    )


app = WsgiToAsgi(app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("tranlate:app", host="127.0.0.1", port=8001, reload=True)
