"""
Extrae la lista de verbos (maya → español) de un PDF como "Los verbos del
maya yucateco actual", ignorando todo lo demás: introducción, explicaciones,
ejemplos de conjugación y oraciones de ejemplo.

Uso (desde la carpeta backend/, con el entorno virtual activado):
    pip install pdfplumber
    python extraer_verbos.py VerbosDelMayaActual.pdf
    python extraer_verbos.py OtroLibro.pdf          # se SUMA a lo anterior
    python extraer_verbos.py Libro.pdf --reemplazar # empieza de cero

Actualiza dos archivos en la carpeta backend/:
    diccionario_verbos.json  el que usa el traductor (mismo formato que
                             diccionario.json: {"es-yua": {...}, "yua-es": {...}})
    verbos_extraidos.csv     todos los verbos con su PDF de origen, sección
                             y página, para revisar en Excel

Cada PDF nuevo se agrega a lo que ya había; correr el mismo PDF otra vez
no duplica nada. El servidor detecta el cambio solo, sin reiniciar.

Cómo distingue un verbo de lo demás: busca renglones con dos columnas
separadas por varios espacios, donde la izquierda es una palabra maya
corta (sin guiones de morfemas) y la derecha empieza con un verbo en
infinitivo en español ("Bramar; Gemir", "Torcerse; cerrarse"). Los
ejemplos como "K-in bis-0-ik    Yo lo llevo" no pasan esos filtros.
"""

import csv
import json
import re
import sys
from pathlib import Path

import pdfplumber

# Renglón con dos columnas: texto, 3+ espacios, texto.
DOS_COLUMNAS = re.compile(r"^\s*(?P<maya>\S.*?)\s{3,}(?P<espanol>\S.*?)\s*$")
# La palabra maya: letras (con acentos y apóstrofes), máximo 3 palabras,
# sin guiones ni números (eso indica un ejemplo de conjugación).
PALABRA_MAYA = re.compile(r"^[A-Za-zÁÉÍÓÚáéíóúÜüÑñ’'´]+(?: [A-Za-zÁÉÍÓÚáéíóúÜüÑñ’'´]+){0,2}$")
# El español debe empezar con un infinitivo: -ar/-er/-ir, con o sin -se/-lo/-la/-le.
INFINITIVO = re.compile(r"^(?:[a-záéíóúñü]+(?:ar|er|ir|ír))(?:se|lo|la|le|los|las|les)?$", re.IGNORECASE)
# Encabezados, para guardar en qué sección y grupo aparece cada verbo:
#   "2.1. VERBOS INTRANSITIVOS"  → sección
#   "Grupo IA.- Los verbos..."   → grupo "Grupo IA"
#   "(GIA1) Verbos que tienen…"  → subgrupo "GIA1"
SECCION = re.compile(r"^\s*(?P<titulo>\d+(?:\.\d+)+\.?\s+[A-ZÁÉÍÓÚ][^.]{3,80}?)\s*$")
# (Los grupos vienen en versalitas, que el PDF guarda como "gruPo ia".)
GRUPO = re.compile(r"^\s*grupo\s+(?P<titulo>[ivx]+[a-z]?)\b", re.IGNORECASE)
SUBGRUPO = re.compile(r"^\s*\((?P<titulo>g[ivx]+[a-z]?\d*)\)", re.IGNORECASE)
INDICE = re.compile(r"\s\d{1,3}\s*$")  # renglones del índice: terminan en número de página
# Pies de página y números de página sueltos.
PIE_DE_PAGINA = re.compile(r"Los verbos del maya yucateco actual|^\s*\d{1,3}\s*$")


def es_verbo(maya: str, espanol: str) -> bool:
    if not PALABRA_MAYA.match(maya) or len(maya) > 30:
        return False
    primera = re.split(r"[\s;,(]", espanol.strip(), maxsplit=1)[0]
    return bool(INFINITIVO.match(primera))


def significados(espanol: str) -> list[str]:
    """'Bramar; Gemir; Quejarse' → ['bramar', 'gemir', 'quejarse']"""
    partes = re.split(r"[;,]", espanol)
    limpias = []
    for parte in partes:
        parte = re.sub(r"\(.*?\)", "", parte).strip().lower()  # quita aclaraciones entre paréntesis
        if parte and parte not in limpias:
            limpias.append(parte)
    return limpias


def extraer(ruta_pdf: Path) -> list[dict]:
    verbos = []
    seccion = grupo = subgrupo = ""
    vistos = set()
    with pdfplumber.open(ruta_pdf) as pdf:
        for numero, pagina in enumerate(pdf.pages, 1):
            # dedupe_chars: los títulos en negritas traen cada letra repetida
            # ("22..11.. VVEERRBBOOSS"); esto deja una sola.
            texto = pagina.dedupe_chars().extract_text(layout=True) or ""
            for renglon in texto.splitlines():
                if not renglon.strip() or PIE_DE_PAGINA.search(renglon):
                    continue
                if (m := SECCION.match(renglon)) and not INDICE.search(renglon):
                    seccion = re.sub(r"\s{2,}", " ", m.group("titulo")).strip().capitalize()
                    seccion = re.sub(r"^([\d.]+\s+)(\w)", lambda x: x.group(1) + x.group(2).upper(), seccion)
                    grupo = subgrupo = ""
                    continue
                if m := GRUPO.match(renglon):
                    grupo, subgrupo = "Grupo " + m.group("titulo").upper(), ""
                if m := SUBGRUPO.match(renglon):
                    subgrupo = m.group("titulo").upper()
                columnas = DOS_COLUMNAS.match(renglon)
                if not columnas:
                    continue
                maya = columnas.group("maya").strip().replace("´", "’")
                espanol = re.sub(r"\s{2,}", " ", columnas.group("espanol")).strip()
                if not es_verbo(maya, espanol):
                    continue
                clave = (maya.lower(), espanol.lower())
                if clave in vistos:
                    continue
                vistos.add(clave)
                verbos.append({
                    "maya": maya,
                    "espanol": espanol,
                    "seccion": " · ".join(x for x in (seccion, grupo, subgrupo) if x),
                    "pagina": numero,
                })
    return verbos


CARPETA_SALIDA = Path(__file__).parent
COLUMNAS = ["maya", "espanol", "seccion", "pagina", "archivo"]


def leer_csv_anterior(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return [{c: fila.get(c, "") for c in COLUMNAS} for fila in csv.DictReader(f)]


def guardar(verbos_nuevos: list[dict], nombre_pdf: str, reemplazar: bool) -> None:
    ruta_csv = CARPETA_SALIDA / "verbos_extraidos.csv"
    ruta_json = CARPETA_SALIDA / "diccionario_verbos.json"

    # Se parte de lo que ya estaba (salvo con --reemplazar). Si este mismo
    # PDF ya se había extraído antes, sus filas viejas se sustituyen por
    # las nuevas, así una versión corregida del PDF no deja restos.
    anteriores = [] if reemplazar else leer_csv_anterior(ruta_csv)
    anteriores = [v for v in anteriores if v["archivo"] != nombre_pdf]
    for v in verbos_nuevos:
        v["archivo"] = nombre_pdf
    vistos = {(v["maya"].lower(), v["espanol"].lower()) for v in anteriores}
    agregados = [v for v in verbos_nuevos if (v["maya"].lower(), v["espanol"].lower()) not in vistos]
    verbos = anteriores + agregados

    with open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: Excel muestra bien los acentos
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS)
        escritor.writeheader()
        escritor.writerows(verbos)

    # El JSON se reconstruye completo desde el CSV, así siempre coinciden.
    es_yua: dict[str, str] = {}
    yua_es: dict[str, str] = {}
    for v in verbos:
        clave_maya = v["maya"].lower()
        # Un mismo verbo maya puede aparecer con significados distintos
        # (ej. "Bis: llevar" y "Bis: agujerar"); se juntan.
        if clave_maya in yua_es and v["espanol"].lower() not in yua_es[clave_maya].lower():
            yua_es[clave_maya] += "; " + v["espanol"]
        else:
            yua_es.setdefault(clave_maya, v["espanol"])
        for significado in significados(v["espanol"]):
            # Si dos verbos mayas significan lo mismo, se guarda el primero.
            es_yua.setdefault(significado, v["maya"])

    temporal = ruta_json.with_suffix(".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump({"es-yua": es_yua, "yua-es": yua_es}, f, ensure_ascii=False, indent=2)
    temporal.replace(ruta_json)  # escritura atómica: el servidor nunca lee un archivo a medias

    repetidos = len(verbos_nuevos) - len(agregados)
    print(f"✓ {len(verbos_nuevos)} verbos encontrados en {nombre_pdf}"
          + (f" ({repetidos} ya estaban por otro PDF)" if repetidos else ""))
    print(f"  Total acumulado: {len(verbos)} verbos de {len({v['archivo'] for v in verbos})} PDF(s)")
    print(f"  {ruta_json.name}: {len(yua_es)} entradas maya→español, {len(es_yua)} español→maya")
    print(f"  {ruta_csv.name}: para revisar en Excel")


def main():
    argumentos = [a for a in sys.argv[1:] if a != "--reemplazar"]
    reemplazar = "--reemplazar" in sys.argv[1:]
    if len(argumentos) != 1:
        sys.exit("Uso: python extraer_verbos.py archivo.pdf [--reemplazar]")
    ruta_pdf = Path(argumentos[0])
    if not ruta_pdf.exists():
        sys.exit(f"No encontré el archivo {ruta_pdf}")
    verbos = extraer(ruta_pdf)
    if not verbos:
        sys.exit("No encontré verbos. Es posible que el PDF sea escaneado (imagen) en vez de texto.")
    guardar(verbos, ruta_pdf.name, reemplazar)


if __name__ == "__main__":
    main()