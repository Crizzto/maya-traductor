"""
Diccionarios locales del traductor.

  - diccionario.json: traducciones verificadas a mano (o aprobadas desde
    las sugerencias de los usuarios). Se relee en cada consulta.
  - Obras de referencia de maya moderno: diccionario_verbos.json (de
    extraer_verbos.py) y referencia_*.json (de extraer_diccionario.py).
    Se recargan solas cuando cambian.
  - diccionario_colonial.json: glosario sacado de vocabularios históricos,
    con ortografía colonial. Se carga una sola vez al arrancar.
"""

import json
import logging
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger("tranlate")

RUTA_DICCIONARIO = Path(__file__).parent / "diccionario.json"
RUTA_DICCIONARIO_COLONIAL = Path(__file__).parent / "diccionario_colonial.json"
RUTA_DICCIONARIO_VERBOS = Path(__file__).parent / "diccionario_verbos.json"


def normalizar(texto: str) -> str:
    """Unifica los distintos caracteres de apóstrofe/saltillo a uno solo."""
    return re.sub(r"['‘’ʻʼ´`]", "'", texto)


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
            normalizar(k).strip().lower(): v for k, v in entradas.items()
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
            normalizar(k).strip().lower(): v for k, v in entradas.items()
        }
    return resultado


DICCIONARIO_COLONIAL = _cargar_diccionario_colonial_una_vez()

_referencias_cache = {"firma": None, "datos": {}}


def _archivos_de_referencia() -> list[Path]:
    """diccionario_verbos.json primero, luego cada referencia_*.json."""
    carpeta = Path(__file__).parent
    archivos = [RUTA_DICCIONARIO_VERBOS] if RUTA_DICCIONARIO_VERBOS.exists() else []
    return archivos + sorted(carpeta.glob("referencia_*.json"))


def _combinar(existente: str, nuevo: str) -> str:
    """Junta significados de varios libros sin repetir ('Janal' + 'janal (en general)')."""
    def base(parte: str) -> str:
        return re.sub(r"\s*\(.*?\)\s*$", "", parte).strip().lower()
    partes = [p.strip() for p in existente.split(";") if p.strip()]
    vistas = {base(p) for p in partes}
    for parte in nuevo.split(";"):
        parte = parte.strip()
        if parte and base(parte) not in vistas:
            partes.append(parte)
            vistas.add(base(parte))
    return "; ".join(partes)


def cargar_referencias() -> dict:
    """
    Carga las obras de referencia de maya moderno: diccionario_verbos.json
    (de extraer_verbos.py) y todos los referencia_*.json (de
    extraer_diccionario.py), combinando lo que dice cada libro.

    Solo vuelve a leer del disco si algún archivo cambió, se agregó o se
    borró, así no hay que reiniciar el servidor después de extraer un PDF.
    """
    archivos = _archivos_de_referencia()
    try:
        firma = tuple((a.name, a.stat().st_mtime) for a in archivos)
    except FileNotFoundError:
        firma = None
    if firma == _referencias_cache["firma"]:
        return _referencias_cache["datos"]

    resultado: dict = {}
    for archivo in archivos:
        try:
            with open(archivo, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("No se pudo leer %s: %s", archivo.name, e)
            continue
        for direccion, entradas in datos.items():
            if not isinstance(entradas, dict) or "-" not in direccion:
                continue  # p. ej. la clave "fuente" con el nombre del PDF
            src, dest = direccion.split("-")
            destino = resultado.setdefault((src, dest), {})
            for clave, valor in entradas.items():
                clave = normalizar(clave).strip().lower()
                destino[clave] = _combinar(destino[clave], valor) if clave in destino else valor

    _referencias_cache.update(firma=firma, datos=resultado)
    logger.info("[DICCIONARIO] Obras de referencia cargadas (%s): %s entradas maya→español, %s español→maya",
                ", ".join(a.name for a in archivos) or "ninguna",
                len(resultado.get(("yua", "es"), {})), len(resultado.get(("es", "yua"), {})))
    return resultado


def _normalizar_busqueda(texto: str) -> str:
    """Minúsculas, apóstrofes unificados y sin signos de puntuación sueltos."""
    texto = normalizar(texto).lower().strip()
    return re.sub(r"[¿?¡!.,;:()\"«»]", " ", texto).strip()


def _palabras(texto: str) -> set:
    return set(_normalizar_busqueda(texto).split())


def llave_maya(texto: str) -> str:
    """
    Forma simplificada de una palabra maya para comparar escrituras
    distintas de la misma palabra. El vocabulario colonial y el maya
    moderno escriben diferente (ej. moderno "ja'" = colonial "haa", moderno
    "k'aak'" = colonial "kak"), así que se igualan: sin acentos ni
    apóstrofes, j→h, k→c, ts→dz, y letras repetidas reducidas a una.
    Es aproximado: sirve para encontrar candidatos, no para afirmar que
    son la misma palabra.
    """
    texto = _normalizar_busqueda(texto)
    texto = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    texto = texto.replace("'", "").replace("ts", "dz").replace("j", "h").replace("k", "c")
    return re.sub(r"(.)\1+", r"\1", texto)


def buscar_en_diccionarios(termino: str, direccion: str = "ambas", limite: int = 12) -> list[dict]:
    """
    Busca un término en el diccionario verificado y en el glosario
    colonial, y devuelve las entradas relacionadas (no solo la exacta):

      1. Coincidencia exacta con la palabra o frase.
      2. Entradas cuya palabra empieza con el término (derivados).
      3. Entradas que contienen el término como palabra completa.
      4. Entradas cuya TRADUCCIÓN contiene el término (búsqueda inversa).

    Si el término está en maya, también compara con ortografía aproximada
    (ver llave_maya) y marca esas entradas con "ortografia_aproximada".

    Dentro de cada grupo van primero las verificadas, luego las de obras
    de referencia modernas y al final las coloniales.
    Lo usa el agente de Gemini para explicar palabras con datos reales.
    """
    objetivo = _normalizar_busqueda(termino)
    if not objetivo:
        return []
    direcciones = [("es", "yua"), ("yua", "es")]
    if direccion in ("es-yua", "yua-es"):
        direcciones = [tuple(direccion.split("-"))]

    fuentes = [
        ("verificado", cargar_diccionario_local()),
        ("referencia", cargar_referencias()),
        ("historico", DICCIONARIO_COLONIAL),
    ]
    grupos: list[list[dict]] = [[], [], [], []]
    vistos = set()

    objetivo_llave = llave_maya(termino)

    def comparar(clave: str, buscado: str) -> int | None:
        if clave == buscado:
            return 0
        if clave.startswith(buscado):
            return 1
        if buscado in clave.split() or (" " in buscado and buscado in clave):
            return 2
        return None

    for nombre_fuente, diccionario in fuentes:
        for src, dest in direcciones:
            for palabra, traduccion in diccionario.get((src, dest), {}).items():
                clave = _normalizar_busqueda(palabra)
                aproximada = False
                grupo = comparar(clave, objetivo)
                if grupo is None and src == "yua" and objetivo_llave:
                    # La palabra está en maya: probar con ortografía aproximada.
                    grupo = comparar(llave_maya(palabra), objetivo_llave)
                    aproximada = grupo is not None
                if grupo is None:
                    if objetivo in _palabras(traduccion) or (" " in objetivo and objetivo in _normalizar_busqueda(traduccion)):
                        grupo = 3
                    elif dest == "yua" and objetivo_llave and objetivo_llave in llave_maya(traduccion).split():
                        grupo, aproximada = 3, True
                    else:
                        continue
                identificador = (nombre_fuente, src, clave, traduccion)
                if identificador in vistos:
                    continue
                vistos.add(identificador)
                entrada = {
                    "fuente": nombre_fuente,
                    "direccion": f"{src}-{dest}",
                    "palabra": palabra,
                    "traduccion": traduccion if len(traduccion) <= 200 else traduccion[:200] + "…",
                }
                if aproximada:
                    entrada["ortografia_aproximada"] = True
                grupos[grupo].append(entrada)

    resultados = []
    for grupo in grupos:
        # Dentro de cada grupo, las entradas más cortas suelen ser las más directas.
        orden_fuente = {"verificado": 0, "referencia": 1, "historico": 2}
        grupo.sort(key=lambda e: (orden_fuente[e["fuente"]], e.get("ortografia_aproximada", False), len(e["palabra"])))
        resultados.extend(grupo)
    return resultados[:limite]