"""
Servidor del Traductor Maya: crea la app de Flask y define los endpoints.
La lógica vive en módulos aparte:

  diccionarios.py  diccionario verificado, glosario colonial y búsqueda
  motor.py         orden de traducción, Azure Translator y cupo mensual
  agente.py        agente conversacional con Gemini y sus herramientas
  voz.py           tokens temporales de Azure Speech
  almacen.py       caché y consumo en SQLite (datos.db)
  proteccion.py    límites de peticiones por IP
"""

import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

import requests
from asgiref.wsgi import WsgiToAsgi
from flask import Flask, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)

import almacen
import proteccion
from agente import GEMINI_LIMITE_DIARIO, MAX_MENSAJE_AGENTE, limpiar_historial, preguntar_al_agente
from diccionarios import normalizar
from motor import AZURE_LIMITE_MENSUAL, azure_detectar_idioma, traducir_con_fuente
from voz import AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, _emitir_token_voz

app = Flask(__name__)
logger = logging.getLogger("tranlate")

# CORS: qué páginas web pueden llamar a este backend desde el navegador.
# En local se permiten localhost y tu red (192.168.x.x) en cualquier
# puerto. En producción define ORIGENES_PERMITIDOS con la URL de tu
# frontend, por ejemplo: https://zacilingua.onrender.com (varias se
# separan con comas). OJO: CORS solo frena a otras páginas web; a un
# script directo lo frenan los límites de proteccion.py.
_origenes_env = os.environ.get("ORIGENES_PERMITIDOS", "").strip()
ORIGENES_PERMITIDOS = (
    [o.strip().rstrip("/") for o in _origenes_env.split(",") if o.strip()]
    if _origenes_env
    else [r"http://localhost(:\d+)?", r"http://127\.0\.0\.1(:\d+)?", r"http://192\.168\.\d+\.\d+(:\d+)?"]
)
CORS(app, resources={r"/api/*": {"origins": ORIGENES_PERMITIDOS}})
proteccion.instalar(app)
almacen.inicializar()

# Tamaños máximos aceptados, para que nadie mande textos gigantes.
MAX_TEXTO_TRADUCIR = 5000
MAX_TEXTO_CHAT = 1000
# Sesiones de voz con Azure Speech por día, sumando a todos los usuarios.
VOZ_LIMITE_DIARIO = int(os.environ.get("VOZ_LIMITE_DIARIO", "150"))

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
    if len(texto) > MAX_TEXTO_TRADUCIR:
        return jsonify(error=f"El texto es demasiado largo (máximo {MAX_TEXTO_TRADUCIR:,} caracteres)."), 400

    resultado, fuente = await traducir_con_fuente(texto, src, dest)
    return jsonify(resultado=resultado, fuente=fuente)


# --- Sugerencias de corrección ---
# Los usuarios proponen traducciones correctas desde la app. Se guardan
# como "pendientes" y NO cambian nada hasta que tú las apruebes con
# revisar_sugerencias.py, que las pasa a diccionario.json.
RUTA_SUGERENCIAS = Path(__file__).parent / "sugerencias_pendientes.json"
_candado_sugerencias = threading.Lock()
_MAX_TEXTO_SUGERENCIA = 500


def leer_sugerencias() -> list:
    try:
        with open(RUTA_SUGERENCIAS, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def guardar_sugerencias(sugerencias: list) -> None:
    temporal = RUTA_SUGERENCIAS.with_suffix(".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(sugerencias, f, ensure_ascii=False, indent=2)
    temporal.replace(RUTA_SUGERENCIAS)  # escritura atómica: no deja el archivo a medias


@app.route("/api/sugerencias", methods=["POST"])
async def api_sugerencias():
    """
    Recibe una corrección propuesta por un usuario. Espera:
    { "original": "...", "traduccion_actual": "...", "sugerencia": "...",
      "direccion": "spanish-maya" | "maya-spanish", "nota": "..." (opcional) }
    """
    datos = request.get_json(silent=True) or {}
    original = (datos.get("original") or "").strip()
    sugerencia = (datos.get("sugerencia") or "").strip()
    actual = (datos.get("traduccion_actual") or "").strip()
    nota = (datos.get("nota") or "").strip()
    src, dest = _resolver_direccion(datos.get("direccion", ""))

    if src is None:
        return jsonify(error="Dirección de traducción inválida."), 400
    if not original or not sugerencia:
        return jsonify(error="Escribe la traducción que propones."), 400
    if max(len(original), len(sugerencia), len(actual), len(nota)) > _MAX_TEXTO_SUGERENCIA:
        return jsonify(error=f"El texto es demasiado largo (máximo {_MAX_TEXTO_SUGERENCIA} caracteres)."), 400
    if normalizar(sugerencia).lower() == normalizar(actual).lower():
        return jsonify(error="La sugerencia es igual a la traducción actual."), 400

    nueva = {
        "id": uuid.uuid4().hex[:10],
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "direccion": f"{src}-{dest}",
        "original": original,
        "traduccion_actual": actual,
        "sugerencia": sugerencia,
        "nota": nota,
    }
    with _candado_sugerencias:
        sugerencias = leer_sugerencias()
        sugerencias.append(nueva)
        guardar_sugerencias(sugerencias)
    logger.info("[SUGERENCIA] %s %r: %r -> %r", nueva["direccion"], original, actual, sugerencia)
    return jsonify(ok=True, id=nueva["id"])


@app.route("/api/chat", methods=["POST"])
async def api_chat():
    """
    Endpoint para la interfaz de chat: no pides dirección, detecta sola
    el idioma del mensaje y traduce al otro. Espera: { "texto": "..." }.
    Responde: { "resultado": "...", "idioma_detectado": "es" | "yua" }.
    """
    datos = request.get_json(silent=True) or {}
    texto = (datos.get("texto") or "").strip()
    if not texto:
        return jsonify(error="Escribe algo para traducir."), 400
    if len(texto) > MAX_TEXTO_CHAT:
        return jsonify(error=f"El mensaje es demasiado largo (máximo {MAX_TEXTO_CHAT:,} caracteres)."), 400

    try:
        idioma_detectado = await asyncio.to_thread(azure_detectar_idioma, texto)
    except Exception as e:
        logger.warning("Detección de idioma falló, asumiendo español: %s", e)
        idioma_detectado = "es"  # respaldo razonable si falla la detección

    src, dest = ("es", "yua") if idioma_detectado == "es" else ("yua", "es")
    resultado, fuente = await traducir_con_fuente(texto, src, dest)
    return jsonify(resultado=resultado, fuente=fuente, idioma_detectado=idioma_detectado)


@app.route("/api/agente", methods=["POST"])
async def api_agente():
    """
    Endpoint del agente conversacional con Gemini. Espera:
    { "mensaje": "...", "historial": [ {"role": "user"|"model", "parts": [{"text": "..."}]}, ... ] }
    Responde: { "respuesta": "..." }
    """
    datos = request.get_json(silent=True) or {}
    mensaje = (datos.get("mensaje") or "").strip()
    if not mensaje:
        return jsonify(error="Escribe algo primero."), 400
    if len(mensaje) > MAX_MENSAJE_AGENTE:
        return jsonify(error=f"El mensaje es demasiado largo (máximo {MAX_MENSAJE_AGENTE:,} caracteres)."), 400
    historial = limpiar_historial(datos.get("historial"))

    try:
        respuesta = await preguntar_al_agente(mensaje, historial)
    except RuntimeError as e:
        # Incluye ErrorGemini: muestra el motivo real en el chat.
        return jsonify(error=str(e)), 502
    except Exception as e:
        logger.exception("El agente falló: %s", e)
        return jsonify(error="El agente no pudo responder en este momento."), 500

    return jsonify(respuesta=respuesta)


@app.route("/api/voz/token", methods=["GET"])
async def api_voz_token():
    """
    Entrega un token temporal de Azure Speech para que el navegador haga
    el reconocimiento de voz en vivo. Responde { "token", "region" }.
    Si Azure Speech no está configurado responde 503, y el frontend usa
    el reconocedor del navegador como respaldo.
    """
    if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        return jsonify(error="Azure Speech no está configurado (faltan AZURE_SPEECH_KEY / AZURE_SPEECH_REGION)."), 503
    # Tope global de sesiones de voz por día (sumando a todos los usuarios).
    # Al llegar, el frontend usa el reconocedor del navegador (Chrome/Edge),
    # que no gasta la cuota de Azure Speech.
    if almacen.uso_obtener("voz_sesiones", almacen.dia_actual()) >= VOZ_LIMITE_DIARIO:
        logger.warning("[VOZ] Se alcanzó el límite diario de %s sesiones de Azure Speech.", VOZ_LIMITE_DIARIO)
        return jsonify(error="Se alcanzó el límite diario de voz con Azure; se usará el reconocedor del navegador."), 503
    try:
        token = await asyncio.to_thread(_emitir_token_voz)
    except requests.HTTPError as e:
        codigo = e.response.status_code if e.response is not None else "?"
        logger.error("[VOZ] Azure Speech rechazó la petición de token (%s).", codigo)
        mensaje = "Azure Speech rechazó la clave; revisa AZURE_SPEECH_KEY y AZURE_SPEECH_REGION." if codigo in (401, 403) else "Azure Speech no respondió bien."
        return jsonify(error=mensaje), 502
    except Exception as e:
        logger.error("[VOZ] No se pudo obtener token de Azure Speech: %s", e)
        return jsonify(error="No se pudo conectar con Azure Speech."), 502
    almacen.uso_sumar("voz_sesiones", 1, almacen.dia_actual())
    return jsonify(token=token, region=AZURE_SPEECH_REGION)


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
        uso=almacen.resumen_uso(),
        limites={"azure_caracteres_mes": AZURE_LIMITE_MENSUAL, "gemini_peticiones_dia": GEMINI_LIMITE_DIARIO, "voz_sesiones_dia": VOZ_LIMITE_DIARIO},
    )


app = WsgiToAsgi(app)

if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 en vez de 127.0.0.1: así otros dispositivos en tu misma red
    # (como tu celular) también pueden conectarse, no solo esta compu.
    uvicorn.run("tranlate:app", host="0.0.0.0", port=8001, reload=True)