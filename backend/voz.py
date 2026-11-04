"""
Tokens temporales de Azure Speech para el modo conferencia.
"""

import logging
import os
import time

import requests

logger = logging.getLogger("tranlate")

# Es un recurso de Azure DISTINTO al Translator: tiene su propia clave y
# región. La clave nunca se manda al navegador; el backend la cambia por
# un token temporal (dura 10 minutos) que es lo único que recibe la página.
AZURE_SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.environ.get("AZURE_SPEECH_REGION", "")
_token_voz = {"valor": "", "expira": 0.0}


def _emitir_token_voz() -> str:
    """Pide a Azure un token de voz; lo reutiliza mientras le queden >1 min."""
    ahora = time.time()
    if _token_voz["valor"] and ahora < _token_voz["expira"]:
        return _token_voz["valor"]
    resp = requests.post(
        f"https://{AZURE_SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken",
        headers={"Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY, "Content-Length": "0"},
        timeout=10,
    )
    resp.raise_for_status()
    _token_voz["valor"] = resp.text
    _token_voz["expira"] = ahora + 9 * 60
    logger.info("[VOZ] Nuevo token de Azure Speech emitido.")
    return resp.text


# --- Texto a voz (para leer las traducciones en iPhone) ---
# En iPhone, la voz del navegador (speechSynthesis) falla: el interruptor de
# silencio la apaga y algunos navegadores no la reproducen. Por eso el
# backend genera la voz con Azure y la página la reproduce como un audio
# normal. No existe voz en maya: se usa una voz en español de México como
# aproximación de la pronunciación.
VOZ_TTS = os.environ.get("VOZ_TTS", "es-MX-DaliaNeural")
# Capa gratuita de Azure: 0.5 millones de caracteres al mes. Al llegar al
# tope, el backend deja de generar voz y la página usa la del navegador.
VOZ_TTS_LIMITE_MENSUAL = int(os.environ.get("VOZ_TTS_LIMITE_MENSUAL", "500000"))
MAX_TEXTO_TTS = 500
_cache_tts: dict[str, bytes] = {}  # frases repetidas no se vuelven a pagar
_MAX_CACHE_TTS = 200


class LimiteVozAlcanzado(RuntimeError):
    pass


def _escapar_xml(texto: str) -> str:
    return (texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def sintetizar_voz(texto: str) -> bytes:
    """Devuelve el audio MP3 del texto, leído con la voz de VOZ_TTS."""
    import almacen

    texto = texto.strip()[:MAX_TEXTO_TTS]
    if texto in _cache_tts:
        return _cache_tts[texto]
    usado = almacen.uso_obtener("voz_tts_caracteres")
    if usado + len(texto) > VOZ_TTS_LIMITE_MENSUAL:
        raise LimiteVozAlcanzado(f"Se alcanzó el tope mensual de voz ({usado:,} caracteres).")

    ssml = (
        "<speak version='1.0' xml:lang='es-MX'>"
        f"<voice name='{VOZ_TTS}'><prosody rate='-5%'>{_escapar_xml(texto)}</prosody></voice>"
        "</speak>"
    )
    resp = requests.post(
        f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={
            "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "zacilingua",
        },
        data=ssml.encode("utf-8"),
        timeout=15,
    )
    resp.raise_for_status()
    almacen.uso_sumar("voz_tts_caracteres", len(texto))
    if len(_cache_tts) >= _MAX_CACHE_TTS:
        _cache_tts.pop(next(iter(_cache_tts)))
    _cache_tts[texto] = resp.content
    logger.info("[VOZ] Audio generado: %s caracteres", len(texto))
    return resp.content
