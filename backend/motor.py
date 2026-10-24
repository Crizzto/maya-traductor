"""
Motor de traducción: decide de dónde sale cada traducción.

Orden: diccionario verificado → glosario colonial → caché (datos.db) →
Azure Translator. También incluye la detección de idioma con Azure y el
control del cupo mensual de caracteres.
"""

import asyncio
import logging
import os

import requests

import almacen
from diccionarios import DICCIONARIO_COLONIAL, cargar_diccionario_local, cargar_referencias, normalizar

logger = logging.getLogger("tranlate")

# --- Azure Translator (motor principal) ---
# Lee la clave y región desde variables de entorno; nunca las escribas
# directo en el código. En local puedes definirlas antes de correr la
# app, y en Render se ponen en Environment del servicio del backend.
AZURE_KEY = os.environ.get("AZURE_TRANSLATOR_KEY", "")
AZURE_REGION = os.environ.get("AZURE_TRANSLATOR_REGION", "")
AZURE_ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

# Azure Translator cobra por CARACTERES (traducir y detectar idioma).
# El conteo del mes se guarda en datos.db, así que sobrevive reinicios.
# No es el contador oficial (ese está en el portal de Azure), pero sirve
# para frenar ANTES de pasarte de la capa gratuita: al llegar a
# AZURE_LIMITE_MENSUAL caracteres, el backend deja de llamar a Azure
# hasta el mes siguiente. Si algún día pasas a un plan de pago y quieres
# más, sube esa variable de entorno.
AZURE_LIMITE_MENSUAL = int(os.environ.get("AZURE_LIMITE_MENSUAL", "2000000"))


class LimiteMensualAlcanzado(RuntimeError):
    pass


def _registrar_caracteres_azure(cantidad: int, motivo: str) -> None:
    total = almacen.uso_sumar("azure_translator_caracteres", cantidad)
    porcentaje = total / AZURE_LIMITE_MENSUAL * 100
    nivel = logging.WARNING if porcentaje >= 80 else logging.INFO
    logger.log(nivel, "[AZURE $] %s: %s caracteres | %s este mes (%.1f%% del límite de %s)",
               motivo, cantidad, f"{total:,}", porcentaje, f"{AZURE_LIMITE_MENSUAL:,}")


def _revisar_cupo_azure(cantidad: int) -> None:
    usado = almacen.uso_obtener("azure_translator_caracteres")
    if usado + cantidad > AZURE_LIMITE_MENSUAL:
        raise LimiteMensualAlcanzado(
            f"No queda cupo mensual de Azure ({usado:,} de {AZURE_LIMITE_MENSUAL:,} caracteres usados)."
        )



def azure_translate(texto: str, src: str, dest: str) -> str:
    """
    Traduce usando Azure Translator (API oficial, autenticada con clave).
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
    _revisar_cupo_azure(len(texto))
    params = {"api-version": "3.0", "from": src, "to": dest}
    cuerpo = [{"Text": texto}]

    resp = requests.post(
        AZURE_ENDPOINT, params=params, headers=headers, json=cuerpo, timeout=10
    )
    resp.raise_for_status()
    datos = resp.json()
    resultado = datos[0]["translations"][0]["text"]

    _registrar_caracteres_azure(len(texto), "traducción")
    return resultado


def azure_detectar_idioma(texto: str) -> str:
    """
    Usa el endpoint /detect de Azure para adivinar el idioma del texto.
    Azure NO tiene un modelo entrenado para reconocer maya yucateco, así
    que no podemos pedirle "¿es español o maya?" directamente. En vez de
    eso, le preguntamos "¿qué tan seguro estás de que es español?" — si
    la respuesta es "sí, es español" con confianza razonable, asumimos
    es->yua; para cualquier otra cosa asumimos maya->es, porque en esta
    app solo existen esos dos idiomas posibles.
    """
    _revisar_cupo_azure(len(texto))
    url = "https://api.cognitive.microsofttranslator.com/detect"
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-Type": "application/json",
    }
    params = {"api-version": "3.0"}
    cuerpo = [{"Text": texto}]
    resp = requests.post(url, params=params, headers=headers, json=cuerpo, timeout=10)
    resp.raise_for_status()
    _registrar_caracteres_azure(len(texto), "detección de idioma")
    datos = resp.json()
    idioma = datos[0].get("language", "")
    confianza = datos[0].get("score", 0)
    logger.info("[DETECCIÓN] idioma=%s confianza=%.2f texto=%r", idioma, confianza, texto)
    return "es" if (idioma == "es" and confianza >= 0.5) else "yua"


# Fuentes posibles de una traducción, de la más a la menos confiable.
# El frontend las muestra como etiqueta junto al resultado.
FUENTE_VERIFICADA = "verificado"   # diccionario.json, revisado a mano
FUENTE_REFERENCIA = "referencia"   # obras de maya moderno extraídas de PDFs
FUENTE_HISTORICA = "historico"     # glosario colonial, ortografía antigua
FUENTE_AUTOMATICA = "automatico"   # Azure Translator
FUENTE_ERROR = "error"


# Signos que se quitan de los extremos para buscar en los diccionarios:
# el reconocimiento de voz agrega un punto final ("Hola.") y la gente
# escribe "¡Hola!" o "¿Bix a beel?". El apóstrofe NO se quita, porque en
# maya es una letra (el saltillo de ja', peek').
_SIGNOS_EXTREMOS = " \t\n.,;:¡!¿?\"«»“”…-"


def clave_de_busqueda(texto: str) -> str:
    return normalizar(texto).strip().lower().strip(_SIGNOS_EXTREMOS)


async def traducir_con_fuente(texto: str, src: str, dest: str) -> tuple[str, str]:
    """
    Traduce y devuelve (resultado, fuente). Intenta en este orden:
    1. Diccionario verificado (diccionario.json).
    2. Obras de referencia de maya moderno (diccionario_verbos.json y referencia_*.json).
    3. Glosario colonial (diccionario_colonial.json).
    4. Caché de traducciones automáticas anteriores (datos.db).
    5. Azure Translator.
    """
    clave = clave_de_busqueda(texto)

    # 1) Diccionario verificado (se recarga cada vez para tomar las
    # correcciones aprobadas sin reiniciar el servidor)
    entrada_local = cargar_diccionario_local().get((src, dest), {})
    if clave in entrada_local:
        logger.info("[FUENTE: diccionario.json] %r -> %r", clave, entrada_local[clave])
        return entrada_local[clave], FUENTE_VERIFICADA

    # 2) Obras de referencia de maya moderno (extraídas de PDFs)
    entrada_referencia = cargar_referencias().get((src, dest), {})
    if clave in entrada_referencia:
        logger.info("[FUENTE: obras de referencia] %r -> %r", clave, entrada_referencia[clave])
        return entrada_referencia[clave], FUENTE_REFERENCIA

    # 3) Glosario colonial
    entrada_colonial = DICCIONARIO_COLONIAL.get((src, dest), {})
    if clave in entrada_colonial:
        logger.info("[FUENTE: diccionario_colonial.json] %r -> %r", clave, entrada_colonial[clave])
        return entrada_colonial[clave], FUENTE_HISTORICA

    # 4) Caché persistente en datos.db (solo traducciones automáticas)
    en_cache = await asyncio.to_thread(almacen.cache_obtener, src, dest, clave)
    if en_cache is not None:
        logger.info("[FUENTE: caché] %r", clave)
        return en_cache, FUENTE_AUTOMATICA

    texto_para_traducir = normalizar(texto)

    # 5) Azure Translator
    try:
        resultado = await asyncio.to_thread(azure_translate, texto_para_traducir, src, dest)
        if resultado:
            logger.info("[FUENTE: Azure Translator] %r -> %r", texto_para_traducir, resultado)
            # No se guarda si Azure devolvió el mismo texto sin traducir.
            if clave_de_busqueda(resultado) != clave:
                await asyncio.to_thread(almacen.cache_guardar, src, dest, clave, resultado)
            return resultado, FUENTE_AUTOMATICA
    except LimiteMensualAlcanzado as e:
        logger.warning("[AZURE $] %s Se omite Azure hasta el próximo mes.", e)
    except Exception as e:
        logger.warning("Azure Translator falló: %s", e)

    return "No se pudo traducir en este momento. Intenta de nuevo más tarde.", FUENTE_ERROR


async def traducir_con_respaldo(texto: str, src: str, dest: str) -> str:
    """
    Versión en texto para el agente de Gemini: le agrega al resultado una
    nota sobre su fuente, para que pueda explicarle al usuario qué tan
    confiable es.
    """
    resultado, fuente = await traducir_con_fuente(texto, src, dest)
    if fuente == FUENTE_HISTORICA:
        return f"{resultado} (fuente histórica, ortografía colonial)"
    if fuente == FUENTE_REFERENCIA:
        return f"{resultado} (obra de referencia de maya moderno)"
    if fuente == FUENTE_VERIFICADA:
        return f"{resultado} (verificada en el diccionario)"
    if fuente == FUENTE_AUTOMATICA:
        return f"{resultado} (traducción automática, puede tener errores)"
    return resultado