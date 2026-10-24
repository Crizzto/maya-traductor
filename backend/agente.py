"""
Agente conversacional con Gemini.

Gemini se encarga de conversar y explicar, pero NO traduce por su cuenta:
cuando necesita datos reales usa dos herramientas que ejecuta nuestro
backend: 'traducir' (motor de traducción) y 'buscar_en_diccionario'
(diccionario verificado + vocabulario colonial).
"""

import asyncio
import logging
import os
import re
import time

import requests

import almacen
from diccionarios import buscar_en_diccionarios
from motor import traducir_con_respaldo

logger = logging.getLogger("tranlate")

MAX_MENSAJE_AGENTE = 2000
MAX_TURNOS_HISTORIAL = 20
MAX_CARACTERES_HISTORIAL = 20000

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Google retira modelos con frecuencia (gemini-2.5-flash se apagó en
# octubre de 2026). Por eso el modelo se puede cambiar con la variable de
# entorno GEMINI_MODELO, y si el configurado ya no existe, el backend
# busca solo un modelo Flash disponible para tu clave.
# Modelo principal fijo y uno de respaldo. Se evita "gemini-flash-latest"
# porque apunta siempre al Flash más nuevo, que es el más saturado. Si el
# principal está saturado o tarda, se salta DE INMEDIATO al respaldo
# (Flash-Lite: más rápido y con mucha menos demanda), sin esperas.
# Ambos se pueden cambiar con variables de entorno.
GEMINI_MODELO_PRINCIPAL = os.environ.get("GEMINI_MODELO", "gemini-3.6-flash")
GEMINI_MODELO_RESPALDO = os.environ.get("GEMINI_MODELO_RESPALDO", "gemini-flash-lite-latest")
_principal_actual = GEMINI_MODELO_PRINCIPAL   # cambia solo si Google retira el modelo
_principal_en_pausa_hasta = 0.0               # tras una saturación, se usa el respaldo un rato
_PAUSA_PRINCIPAL = 120                        # segundos
_modelos_sin_thinking: set[str] = set()       # modelos que no aceptan thinkingLevel
# Segundos máximos por llamada a Gemini y por pregunta completa (una
# pregunta puede requerir varias llamadas si usa herramientas).
GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "25"))
GEMINI_TIEMPO_MAXIMO = int(os.environ.get("GEMINI_TIEMPO_MAXIMO", "50"))

INSTRUCCION_AGENTE = (
    "Eres un asistente bilingüe que ayuda a la gente a entender y usar el "
    "maya yucateco y el español. Puedes explicar palabras, gramática, "
    "contexto cultural, y mantener una conversación natural. "
    "IMPORTANTE: tú NO sabes traducir con precisión al maya yucateco por "
    "tu cuenta (es un idioma de muy bajos recursos y podrías inventar "
    "traducciones incorrectas). Cada vez que necesites una traducción "
    "real y confiable entre español y maya, SIEMPRE usa la herramienta "
    "'traducir' en vez de traducir tú mismo. Si el usuario pide varias "
    "cosas, puedes usar la herramienta varias veces. Puedes explicar, "
    "comentar o dar contexto sobre el resultado que te devuelva la "
    "herramienta, pero el texto traducido en sí debe venir de ella, no de "
    "ti. Para explicar el significado de una palabra en maya, sus partes, "
    "variantes o palabras relacionadas, usa la herramienta "
    "'buscar_en_diccionario', que consulta el diccionario verificado, obras "
    "de referencia de maya moderno y el vocabulario colonial; apóyate en lo que devuelva en vez de en tu "
    "memoria, y si no encuentra nada, dilo con honestidad. "
    "Las herramientas indican la fuente de cada resultado: si dice "
    "'fuente histórica, ortografía colonial', avisa que la escritura moderna "
    "puede ser distinta; si dice 'traducción automática', menciona "
    "brevemente que conviene confirmarla con un hablante. "
    "Sé eficiente con las herramientas: normalmente basta una búsqueda o una "
    "traducción; si necesitas varias, pídelas todas a la vez en lugar de una "
    "tras otra. "
    "Responde siempre en español, de forma breve y amable. "
    "FORMATO: usa párrafos cortos separados por una línea en blanco; si das "
    "varias opciones o un desglose, ponlos como lista con un elemento por "
    "línea (empezando con '- '); escribe en **negritas** las palabras o "
    "frases en maya. No uses títulos ni tablas. "
    "Si explicas el significado de cada parte de una frase en maya (un "
    "desglose) y eso no vino de la herramienta, aclara en una frase que es "
    "una explicación orientativa."
)

HERRAMIENTA_TRADUCIR = {
    "function_declarations": [
        {
            "name": "traducir",
            "description": "Traduce texto entre español y maya yucateco usando el motor de traducción verificado del sistema (diccionario local, glosario histórico, o Azure Translator).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "texto": {"type": "STRING", "description": "El texto a traducir."},
                    "direccion": {
                        "type": "STRING",
                        "enum": ["es-yua", "yua-es"],
                        "description": "'es-yua' para traducir de español a maya, 'yua-es' para maya a español.",
                    },
                },
                "required": ["texto", "direccion"],
            },
        },
        {
            "name": "buscar_en_diccionario",
            "description": "Busca una palabra o frase en el diccionario verificado del proyecto y en el vocabulario colonial del maya. Devuelve la entrada exacta y entradas relacionadas (derivados, frases que la contienen, y entradas cuya traducción la menciona). Úsala para explicar significados, partes de una palabra o variantes.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "termino": {"type": "STRING", "description": "La palabra o frase a buscar, en español o en maya."},
                    "direccion": {
                        "type": "STRING",
                        "enum": ["es-yua", "yua-es", "ambas"],
                        "description": "'es-yua' si el término está en español, 'yua-es' si está en maya, 'ambas' si no estás seguro.",
                    },
                },
                "required": ["termino"],
            },
        },
    ]
}

_MAX_RONDAS_HERRAMIENTA = 4
# Tope global de llamadas a Gemini por día (sumando a todos los usuarios),
# por si alguien abusa del agente aunque respete el límite por IP.
GEMINI_LIMITE_DIARIO = int(os.environ.get("GEMINI_LIMITE_DIARIO", "500"))


class ErrorGemini(RuntimeError):
    """Error de la API de Gemini con el mensaje real que devolvió Google."""


def _cabeceras_gemini() -> dict:
    return {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}


def _buscar_modelo_flash_disponible(excluir: str = "") -> str:
    """
    Pregunta a Google qué modelos tiene tu clave y elige un Flash de texto.
    Prefiere Flash normal (estable antes que preview, más nuevo primero) y
    deja Flash-Lite como último recurso. 'excluir' sirve para saltarse el
    modelo que está saturado en ese momento.
    """
    resp = requests.get(f"{GEMINI_BASE}/models", headers=_cabeceras_gemini(),
                        params={"pageSize": 1000}, timeout=15)
    resp.raise_for_status()
    candidatos = []
    for m in resp.json().get("models", []):
        nombre = m.get("name", "").removeprefix("models/")
        metodos = m.get("supportedGenerationMethods", [])
        if "generateContent" not in metodos or "flash" not in nombre or nombre == excluir:
            continue
        if any(x in nombre for x in ("image", "tts", "live", "audio", "embedding", "cyber")):
            continue
        candidatos.append(nombre)
    if not candidatos:
        raise ErrorGemini("No encontré ningún modelo Flash disponible para tu API key.")
    candidatos.sort(key=lambda n: (
        "lite" in n,
        "preview" in n or "exp" in n,
        [-int(x) for x in re.findall(r"\d+", n)[:2]],
    ))
    logger.info("[AGENTE] Modelos Flash disponibles: %s", candidatos)
    return candidatos[0]


def _gemini_llamar(contenidos: list, limite: float) -> dict:
    """
    Hace UNA llamada a Gemini. Prueba primero el modelo principal y, si está
    saturado, sin cupo o tarda, pasa de inmediato al de respaldo. 'limite'
    es el momento (time.monotonic) en que se acaba el tiempo de la pregunta.
    """
    global _principal_actual, _principal_en_pausa_hasta
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Falta la variable de entorno GEMINI_API_KEY. Recuerda definirla "
            "en la MISMA ventana de PowerShell donde corres iniciar.py."
        )
    if almacen.uso_obtener("gemini_peticiones", almacen.dia_actual()) >= GEMINI_LIMITE_DIARIO:
        raise ErrorGemini("El agente alcanzó su límite de uso por hoy. Vuelve a intentarlo mañana o usa el chat simple.")

    modelos = [_principal_actual, GEMINI_MODELO_RESPALDO]
    if time.monotonic() < _principal_en_pausa_hasta:
        modelos = [GEMINI_MODELO_RESPALDO, _principal_actual]

    ultimo_error = "Gemini no respondió."
    resp = None
    for indice, modelo in enumerate(modelos):
        intentos_config = 0
        while True:
            restante = limite - time.monotonic()
            if restante < 3:
                raise ErrorGemini("Gemini está tardando demasiado en responder. Intenta de nuevo en un momento o usa el chat simple.")
            cuerpo = {
                "system_instruction": {"parts": [{"text": INSTRUCCION_AGENTE}]},
                "contents": contenidos,
                "tools": [HERRAMIENTA_TRADUCIR],
            }
            # Pensamiento bajo: para explicar una traducción no hace falta
            # que el modelo razone mucho, y así responde bastante más rápido.
            if modelo not in _modelos_sin_thinking:
                cuerpo["generationConfig"] = {"thinkingConfig": {"thinkingLevel": "low"}}

            almacen.uso_sumar("gemini_peticiones", 1, almacen.dia_actual())
            inicio = time.monotonic()
            try:
                resp = requests.post(f"{GEMINI_BASE}/models/{modelo}:generateContent",
                                     headers=_cabeceras_gemini(), json=cuerpo,
                                     timeout=(10, min(GEMINI_TIMEOUT, restante)))
            except requests.Timeout:
                ultimo_error = f"{modelo} tardó demasiado"
                logger.warning("[AGENTE] %r tardó más de %ss.", modelo, int(min(GEMINI_TIMEOUT, restante)))
                break  # al siguiente modelo
            except requests.RequestException as e:
                raise ErrorGemini(f"No se pudo conectar con Gemini: {e}")

            if resp.ok:
                logger.info("[AGENTE] %r respondió en %.1fs%s", modelo, time.monotonic() - inicio,
                            " (respaldo)" if modelo == GEMINI_MODELO_RESPALDO else "")
                return resp.json()

            intentos_config += 1
            texto_error = resp.text.lower()
            if resp.status_code == 400 and "thinking" in texto_error and modelo not in _modelos_sin_thinking and intentos_config < 3:
                logger.info("[AGENTE] %r no acepta thinkingLevel; se omite.", modelo)
                _modelos_sin_thinking.add(modelo)
                continue
            if resp.status_code == 404 and modelo == _principal_actual and intentos_config < 3:
                nuevo_principal = _buscar_modelo_flash_disponible(excluir=modelo)
                logger.warning("[AGENTE] %r ya no existe; ahora el principal es %r. "
                               "Conviene fijarlo con la variable GEMINI_MODELO.", modelo, nuevo_principal)
                _principal_actual = modelo = nuevo_principal
                continue
            break  # error que se resuelve cambiando de modelo (o no tiene solución)

        # Este modelo falló: decidir si vale la pena probar el siguiente.
        if resp is not None and not resp.ok:
            try:
                detalle = resp.json().get("error", {}).get("message", resp.text)
            except ValueError:
                detalle = resp.text
            logger.warning("[AGENTE] %r respondió %s: %s", modelo, resp.status_code, detalle[:200])
            if resp.status_code in (400, 403) and "api key" in detalle.lower():
                raise ErrorGemini("Google rechazó tu GEMINI_API_KEY. Revisa que esté bien copiada.")
            if resp.status_code not in (429, 500, 503, 404):
                raise ErrorGemini(f"Gemini respondió {resp.status_code}: {detalle}")
            ultimo_error = f"{modelo} respondió {resp.status_code}"
        if modelo == _principal_actual:
            _principal_en_pausa_hasta = time.monotonic() + _PAUSA_PRINCIPAL
        if indice + 1 < len(modelos):
            logger.warning("[AGENTE] Pasando a %r (%s).", modelos[indice + 1], ultimo_error)
        resp = None

    logger.error("[AGENTE] Ningún modelo respondió: %s", ultimo_error)
    raise ErrorGemini("Los servidores de Gemini están saturados ahora mismo. Intenta de nuevo en unos minutos o usa el chat simple.")


async def _ejecutar_herramienta(nombre: str, args: dict) -> dict:
    """Ejecuta la herramienta que pidió Gemini con nuestros datos reales."""
    if nombre == "traducir":
        direccion = args.get("direccion")
        if direccion not in ("es-yua", "yua-es"):
            return {"error": "Dirección no válida; usa 'es-yua' o 'yua-es'."}
        src, dest = direccion.split("-")
        resultado = await traducir_con_respaldo(str(args.get("texto", ""))[:MAX_MENSAJE_AGENTE], src, dest)
        logger.info("[AGENTE] Gemini pidió traducir %r (%s) -> %r", args.get("texto"), direccion, resultado)
        return {"resultado": resultado}

    if nombre == "buscar_en_diccionario":
        termino = str(args.get("termino", ""))[:200]
        direccion = args.get("direccion", "ambas")
        encontrados = await asyncio.to_thread(buscar_en_diccionarios, termino, direccion)
        logger.info("[AGENTE] Gemini buscó %r en diccionarios (%s): %s resultado(s)", termino, direccion, len(encontrados))
        etiquetas = {
            "verificado": "verificada",
            "referencia": "obra de referencia de maya moderno",
            "historico": "fuente histórica, ortografía colonial",
        }
        if not encontrados:
            return {"resultados": [], "nota": "No hay entradas para ese término en los diccionarios del proyecto."}
        return {"resultados": [
            {
                "palabra": e["palabra"], "traduccion": e["traduccion"], "direccion": e["direccion"],
                "fuente": etiquetas[e["fuente"]] + (" (coincidencia por escritura parecida, confirmar)" if e.get("ortografia_aproximada") else ""),
            }
            for e in encontrados
        ]}

    return {"error": f"Herramienta desconocida: {nombre}"}


async def preguntar_al_agente(mensaje: str, historial: list) -> str:
    """
    Manda el mensaje a Gemini con la herramienta de traducción disponible.
    Repite el ciclo mientras Gemini siga pidiendo traducciones (puede pedir
    varias a la vez o una tras otra), ejecutando cada una con nuestro motor
    real (diccionario + Azure), hasta que entregue su respuesta en texto.
    """
    contenidos = list(historial) + [{"role": "user", "parts": [{"text": mensaje}]}]
    limite = time.monotonic() + GEMINI_TIEMPO_MAXIMO

    for _ in range(_MAX_RONDAS_HERRAMIENTA):
        datos = await asyncio.to_thread(_gemini_llamar, contenidos, limite)
        candidatos = datos.get("candidates") or []
        if not candidatos or "content" not in candidatos[0]:
            motivo = (datos.get("promptFeedback") or {}).get("blockReason") or (candidatos[0].get("finishReason") if candidatos else "sin respuesta")
            logger.warning("[AGENTE] Respuesta vacía de Gemini: %s", motivo)
            return "No pude generar una respuesta para eso. Intenta reformularlo."

        contenido_modelo = candidatos[0]["content"]
        partes = contenido_modelo.get("parts", [])
        llamadas = [p["functionCall"] for p in partes if "functionCall" in p]

        if not llamadas:
            texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
            return texto.strip() or "No supe cómo responder eso."

        # Se reenvía el contenido del modelo TAL CUAL (incluye la firma de
        # pensamiento que Gemini exige en la siguiente vuelta).
        contenidos.append(contenido_modelo)

        respuestas = []
        for llamada in llamadas:
            contenido_respuesta = await _ejecutar_herramienta(llamada.get("name", ""), llamada.get("args") or {})
            respuesta = {"functionResponse": {"name": llamada.get("name", "traducir"), "response": contenido_respuesta}}
            if "id" in llamada:
                respuesta["functionResponse"]["id"] = llamada["id"]
            respuestas.append(respuesta)

        contenidos.append({"role": "user", "parts": respuestas})

    return "La consulta requirió demasiados pasos. Intenta preguntar algo más concreto."


def limpiar_historial(historial) -> list:
    """
    El historial lo manda el navegador, así que no se confía en él tal
    cual: solo se aceptan turnos de texto con rol "user" o "model" (nada de
    llamadas a herramientas inventadas), se conservan los últimos turnos y
    se recorta si en total es demasiado largo.
    """
    if not isinstance(historial, list):
        return []
    limpio = []
    for turno in historial[-MAX_TURNOS_HISTORIAL:]:
        if not isinstance(turno, dict) or turno.get("role") not in ("user", "model"):
            continue
        partes = turno.get("parts")
        if not isinstance(partes, list):
            continue
        texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and isinstance(p.get("text"), str))
        if texto.strip():
            limpio.append({"role": turno["role"], "parts": [{"text": texto[:MAX_MENSAJE_AGENTE * 2]}]})
    # Si aún es muy largo, se descartan los turnos más viejos.
    while limpio and sum(len(t["parts"][0]["text"]) for t in limpio) > MAX_CARACTERES_HISTORIAL:
        limpio.pop(0)
    # Gemini espera que la conversación empiece con un turno del usuario.
    while limpio and limpio[0]["role"] != "user":
        limpio.pop(0)
    return limpio