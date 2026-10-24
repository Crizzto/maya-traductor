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
