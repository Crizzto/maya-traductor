"""
Extrae las traducciones de un diccionario maya-español en PDF con
formato de "entradas en párrafo", como el Diccionario Maya Popular del
INEA. Cada entrada se ve así:

    Baaj V. Tr. Clavar: baj in xaanab: clava mi zapato. // S. Tuza.
    ^^^^ ^^^^^ ^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^  ^^  ^^^^^^^
    palabra  tipo  traducción     ejemplo de uso        otro significado
    (negritas)

El script se queda con la palabra y su traducción, y descarta los
ejemplos de uso, las explicaciones largas y los sentidos figurados.

Uso (desde la carpeta backend/, con el entorno virtual activado):
    pip install pdfplumber
    python extraer_diccionario.py diccionario.pdf

Detecta solo las partes del diccionario buscando sus portadas
("MAYA—ESPAÑOL" y "ESPAÑOL-MAYA"). Si un PDF no tiene portadas así,
puedes indicar las páginas a mano:
    python extraer_diccionario.py dicc.pdf --maya-espanol 25-164 --espanol-maya 165-215

Genera en backend/, con el nombre del PDF:
    referencia_<nombre>.json  lo usa el traductor (como fuente "Obra de referencia")
    referencia_<nombre>.csv   todas las entradas para revisar en Excel,
                              incluidas las que no pasaron al JSON y por qué

Volver a correr el mismo PDF sustituye sus archivos; otros PDFs generan
los suyos, así que se acumulan. El servidor los recarga solo.
"""

import csv
import json
import re
import sys
from pathlib import Path

import pdfplumber

CARPETA_SALIDA = Path(__file__).parent
MAX_PALABRAS_TRADUCCION = 8

PORTADA_MAYA_ESPANOL = re.compile(r"MAYA\s*[—–-]\s*ESPAÑOL", re.IGNORECASE)
PORTADA_ESPANOL_MAYA = re.compile(r"ESPAÑOL\s*[—–-]\s*MAYA", re.IGNORECASE)

# Abreviaturas gramaticales que van después de la palabra: "S.", "V. Tr.",
# "Adj.", "Pron. Interr.", etc. Se aceptan varias seguidas.
ABREVIATURAS = (
    r"S|V|Adj|Adv|Part|Pron|Prep|Conj|Interj|Num|Núm|Art|Tr|Intr|Interr|Fig|"
    r"Loc|Pl|Dem|Pos|Aux|Cl|Clas|Sust|Exp|Expr|Onom|Rel|Neg|Imp|Pas|Ref|Recip|F|M|Fem|Masc"
)
ETIQUETA = re.compile(rf"^\s*(?P<etiqueta>(?:(?:{ABREVIATURAS})\.\s*)+)", re.IGNORECASE)
# Señales de que un texto está en maya y no en español.
# Definiciones que explican en vez de traducir.
EXPLICACION = re.compile(
    r"^(partícula|particula|clasificador|sufijo|prefijo|nombre de|que |se usa|se dice|"
    r"palabra|expresión|forma |maya que|término|consonante|vocal|letra|población|pueblo de|municipio)",
    re.IGNORECASE,
)
PARECE_MAYA = re.compile(r"[’']|aa|ee|ii|oo|uu|áa|ée|íi|óo|úu|\bk[aeiou]|\bts|\bx[aeiouáéíóú]", re.IGNORECASE)


# ---------------------------------------------------------------- lectura

def columnas_de(pagina) -> list[tuple[float, float]]:
    """Encuentra el espacio vacío entre las dos columnas de la página."""
    ancho = pagina.width
    palabras = pagina.extract_words()
    if not palabras:
        return []
    ocupado = [False] * (int(ancho) + 1)
    for p in palabras:
        for x in range(int(p["x0"]), min(int(p["x1"]) + 1, len(ocupado))):
            ocupado[x] = True
    mejor_inicio, mejor_largo, inicio = None, 0, None
    for x in range(int(ancho * 0.35), int(ancho * 0.65)):
        if not ocupado[x]:
            inicio = x if inicio is None else inicio
            if x - inicio + 1 > mejor_largo:
                mejor_inicio, mejor_largo = inicio, x - inicio + 1
        else:
            inicio = None
    if mejor_largo < 4:  # no hay hueco claro: página de una sola columna
        return [(0, ancho)]
    corte = mejor_inicio + mejor_largo / 2
    return [(0, corte), (corte, ancho)]


def renglones_de(pagina, x0: float, x1: float) -> list[list[dict]]:
    """Palabras de una columna agrupadas en renglones, con su tipo de letra."""
    recorte = pagina.crop((x0, 0, x1, pagina.height))
    palabras = recorte.extract_words(extra_attrs=["fontname", "size"])
    renglones: list[list[dict]] = []
    for p in sorted(palabras, key=lambda p: (round(p["top"]), p["x0"])):
        if renglones and abs(renglones[-1][0]["top"] - p["top"]) < 3:
            renglones[-1].append(p)
        else:
            renglones.append([p])
    return [sorted(r, key=lambda p: p["x0"]) for r in renglones]


def es_negrita(palabra: dict) -> bool:
    return "bold" in palabra["fontname"].lower()


def entradas_de_pagina(pagina) -> list[tuple[str, str]]:
    """Devuelve [(palabra en negritas, resto del texto de la entrada)]."""
    entradas: list[list] = []
    for x0, x1 in columnas_de(pagina):
        renglones = renglones_de(pagina, x0, x1)
        if not renglones:
            continue
        # Las entradas empiezan pegadas al margen de la columna; los
        # renglones que continúan una entrada van con sangría. Esto evita
        # confundir ejemplos en maya (que también van en negritas) con
        # entradas nuevas.
        margen = min(r[0]["x0"] for r in renglones if not all(p["size"] > 14 for p in r))
        for renglon in renglones:
            texto = " ".join(p["text"] for p in renglon)
            # Letras grandes de sección ("B") y números de página.
            if all(p["size"] > 14 for p in renglon) or re.fullmatch(r"\d{1,3}", texto):
                continue
            if es_negrita(renglon[0]) and renglon[0]["x0"] - margen < 2.5:
                cabeza = []
                for p in renglon:
                    if not es_negrita(p):
                        break
                    cabeza.append(p["text"])
                resto = " ".join(p["text"] for p in renglon[len(cabeza):])
                entradas.append([" ".join(cabeza), resto])
            elif entradas:
                anterior = entradas[-1]
                # Une palabras partidas con guion al final del renglón.
                if anterior[1].endswith("-") and not anterior[1].endswith(" -"):
                    anterior[1] = anterior[1][:-1] + texto
                else:
                    anterior[1] += " " + texto
    return [(c.strip(), r.strip()) for c, r in entradas]


# ---------------------------------------------------------------- análisis

def limpiar_palabra(cabeza: str) -> str:
    """'Antiguo, gua' → 'Antiguo'; quita puntuación sobrante."""
    cabeza = re.sub(r",\s*\w{1,4}$", "", cabeza.strip())
    return cabeza.strip(" .,:;")


def sentidos(cuerpo: str, direccion: str) -> list[dict]:
    """Separa los significados ('//') y saca la traducción de cada uno."""
    resultado = []
    for sentido in cuerpo.split("//"):
        sentido = sentido.strip()
        if not sentido:
            continue
        m = ETIQUETA.match(sentido)
        etiqueta = m.group("etiqueta").strip() if m else ""
        texto = sentido[m.end():] if m else sentido
        # "V. Tr Agrandar": abreviatura sin punto pegada a la traducción.
        if t := re.match(r"^(Tr|Intr|Interr)\s+", texto):
            etiqueta = (etiqueta + " " + t.group(1) + ".").strip()
            texto = texto[t.end():]
        motivo = ""
        matiz = ""
        if "fig" in etiqueta.lower():
            motivo = "sentido figurado"

        def hasta_punto(t: str) -> str:
            t = re.split(r"\.\s", t + " ", maxsplit=1)[0]
            return re.sub(r"\s+", " ", t).strip(" .;,")

        antes, _, despues = texto.partition(":")
        antes, despues_corto = hasta_punto(antes), hasta_punto(despues.split(":")[0])
        # En la parte español→maya hay entradas con matiz, como
        # "Comer V. En general: janal. // Devorando: maak'": lo de antes de
        # ":" es el matiz en español y la traducción va después. Se detecta
        # porque lo de antes NO parece maya y, o lo de después SÍ parece
        # maya, o hay un solo ":" con algo corto después (cuando hay
        # ejemplo, hay dos: "Amable Adj. Uts: es muy amable...: jach uts...").
        con_matiz = despues_corto and not PARECE_MAYA.search(antes) and (
            PARECE_MAYA.search(despues_corto)
            or (texto.count(":") == 1 and len(despues_corto.split()) <= 5)
        )
        if direccion == "es-yua" and con_matiz:
            matiz, traduccion = antes, despues_corto
        else:
            # Caso normal: la traducción es lo que va antes del primer ":"
            # (después vienen ejemplos) y del primer punto (después vienen
            # "También se dice...", "Ver ...").
            traduccion = antes
        if not traduccion:
            motivo = motivo or "sin traducción"
        elif EXPLICACION.match(traduccion):
            motivo = motivo or "es una explicación, no una traducción"
        elif len(traduccion.split()) > MAX_PALABRAS_TRADUCCION:
            motivo = motivo or "es una explicación, no una traducción"
        elif direccion == "yua-es" and PARECE_MAYA.search(traduccion):
            motivo = motivo or "es un ejemplo en maya, no una traducción"
        if re.search(r"consonante|vocal del alfabeto|letra del alfabeto", traduccion, re.IGNORECASE):
            motivo = motivo or "es una letra del alfabeto"
        resultado.append({"etiqueta": etiqueta, "traduccion": traduccion, "matiz": matiz, "motivo": motivo})
    return resultado


def extraer(ruta_pdf: Path, rangos: dict) -> list[dict]:
    filas = []
    with pdfplumber.open(ruta_pdf) as pdf:
        direccion = None
        for numero, pagina in enumerate(pdf.pages, 1):
            pagina = pagina.dedupe_chars()
            if rangos:
                direccion = next((d for d, (a, b) in rangos.items() if a <= numero <= b), None)
            else:
                texto = (pagina.extract_text() or "")[:200]
                if PORTADA_MAYA_ESPANOL.search(texto) and len(texto) < 80:
                    direccion = "yua-es"
                    continue
                if PORTADA_ESPANOL_MAYA.search(texto) and len(texto) < 80:
                    direccion = "es-yua"
                    continue
            if not direccion:
                continue
            for cabeza, cuerpo in entradas_de_pagina(pagina):
                palabra = limpiar_palabra(cabeza)
                if not palabra or len(palabra) > 40:
                    continue
                for s in sentidos(cuerpo, direccion):
                    filas.append({
                        "direccion": direccion,
                        "palabra": palabra,
                        "tipo": s["etiqueta"],
                        "traduccion": s["traduccion"],
                        "matiz": s["matiz"],
                        "usada": "no" if s["motivo"] else "sí",
                        "motivo": s["motivo"],
                        "pagina": numero,
                    })
    return filas


def separar(traduccion: str) -> list[str]:
    """'Cubrir, tapar' → ['cubrir', 'tapar']"""
    partes = [re.sub(r"\(.*?\)", "", p).strip().lower() for p in re.split(r"[;,]", traduccion)]
    return [p for p in partes if p]


def guardar(filas: list[dict], nombre_pdf: str) -> None:
    base = re.sub(r"[^\w-]+", "_", Path(nombre_pdf).stem).strip("_").lower()
    ruta_csv = CARPETA_SALIDA / f"referencia_{base}.csv"
    ruta_json = CARPETA_SALIDA / f"referencia_{base}.json"

    with open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        escritor.writeheader()
        escritor.writerows(filas)

    es_yua: dict[str, str] = {}
    yua_es: dict[str, str] = {}
    usadas = [f for f in filas if f["usada"] == "sí"]

    def agregar(diccionario: dict, clave: str, valor: str):
        clave = clave.strip().lower()
        if not clave:
            return
        if clave in diccionario:
            if valor.lower() not in diccionario[clave].lower():
                diccionario[clave] += "; " + valor
        else:
            diccionario[clave] = valor

    # Primero las entradas directas de cada parte del diccionario...
    for f in usadas:
        valor = f["traduccion"] + (f" ({f['matiz'].lower()})" if f["matiz"] else "")
        agregar(yua_es if f["direccion"] == "yua-es" else es_yua, f["palabra"], valor)
    # ...y después, para huecos, las inversas (de la otra parte).
    for f in usadas:
        destino = es_yua if f["direccion"] == "yua-es" else yua_es
        for parte in separar(f["traduccion"]):
            destino.setdefault(parte, f["palabra"])

    temporal = ruta_json.with_suffix(".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump({"fuente": nombre_pdf, "es-yua": es_yua, "yua-es": yua_es}, f, ensure_ascii=False, indent=2)
    temporal.replace(ruta_json)

    por_parte = {d: sum(1 for f in usadas if f["direccion"] == d) for d in ("yua-es", "es-yua")}
    print(f"✓ {len(usadas)} traducciones útiles de {len(filas)} sentidos encontrados en {nombre_pdf}")
    print(f"  Parte maya→español: {por_parte['yua-es']} · parte español→maya: {por_parte['es-yua']}")
    print(f"  {ruta_json.name}: {len(yua_es)} entradas maya→español, {len(es_yua)} español→maya")
    print(f"  {ruta_csv.name}: para revisar en Excel (columna 'usada' y 'motivo')")


def leer_rango(texto: str) -> tuple[int, int]:
    a, b = texto.split("-")
    return int(a), int(b)


def main():
    argumentos = sys.argv[1:]
    rangos = {}
    for opcion, direccion in (("--maya-espanol", "yua-es"), ("--espanol-maya", "es-yua")):
        if opcion in argumentos:
            i = argumentos.index(opcion)
            rangos[direccion] = leer_rango(argumentos[i + 1])
            del argumentos[i:i + 2]
    if len(argumentos) != 1:
        sys.exit("Uso: python extraer_diccionario.py archivo.pdf [--maya-espanol 25-164] [--espanol-maya 165-215]")
    ruta_pdf = Path(argumentos[0])
    if not ruta_pdf.exists():
        sys.exit(f"No encontré el archivo {ruta_pdf}")
    filas = extraer(ruta_pdf, rangos)
    if not filas:
        sys.exit("No encontré entradas. Si el PDF no tiene portadas 'MAYA—ESPAÑOL' / 'ESPAÑOL-MAYA', "
                 "indica las páginas con --maya-espanol y --espanol-maya.")
    guardar(filas, ruta_pdf.name)


if __name__ == "__main__":
    main()