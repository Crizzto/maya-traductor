"""
Revisa las correcciones que los usuarios propusieron desde la app.

Uso (desde la carpeta backend/):
    python revisar_sugerencias.py

Por cada sugerencia pendiente puedes:
    a = aprobar (se agrega a diccionario.json como traducción verificada)
    e = editar el texto antes de aprobarlo
    r = rechazar
    s = saltar (se queda pendiente para después)
    q = salir

Las aprobadas y rechazadas se mueven a sugerencias_revisadas.json para
que quede registro. No hace falta reiniciar el servidor: diccionario.json
se vuelve a leer en cada traducción.
"""

import json
import re
from datetime import datetime
from pathlib import Path

CARPETA = Path(__file__).parent
RUTA_PENDIENTES = CARPETA / "sugerencias_pendientes.json"
RUTA_REVISADAS = CARPETA / "sugerencias_revisadas.json"
RUTA_DICCIONARIO = CARPETA / "diccionario.json"

NOMBRES = {"es": "Español", "yua": "Maya"}


def normalizar(texto: str) -> str:
    return re.sub(r"['‘’ʻ]", "'", texto)


def leer(ruta: Path, vacio):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return vacio


def guardar(ruta: Path, datos) -> None:
    temporal = ruta.with_suffix(".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    temporal.replace(ruta)


def agregar_al_diccionario(diccionario: dict, direccion: str, original: str, traduccion: str) -> None:
    entradas = diccionario.setdefault(direccion, {})
    clave = normalizar(original).strip().lower()
    anterior = entradas.get(clave)
    if anterior and anterior != traduccion:
        print(f"   (reemplaza la entrada anterior: {anterior!r})")
    entradas[clave] = traduccion.strip()


def preguntar(texto: str, opciones: str) -> str:
    while True:
        respuesta = input(texto).strip().lower()
        if respuesta in opciones:
            return respuesta
        print(f"   Opción no válida. Usa una de: {', '.join(opciones)}")


def main():
    pendientes = leer(RUTA_PENDIENTES, [])
    if not pendientes:
        print("No hay sugerencias pendientes. 🎉")
        return

    diccionario = leer(RUTA_DICCIONARIO, {})
    revisadas = leer(RUTA_REVISADAS, [])
    procesadas = set()
    aprobadas = 0

    print(f"Hay {len(pendientes)} sugerencia(s) pendiente(s).\n")
    for i, s in enumerate(pendientes, 1):
        src, dest = s["direccion"].split("-")
        print("─" * 60)
        print(f"[{i}/{len(pendientes)}]  {s['fecha']}   ({NOMBRES[src]} → {NOMBRES[dest]})")
        print(f"  Original:           {s['original']}")
        print(f"  Traducción actual:  {s['traduccion_actual'] or '—'}")
        print(f"  Sugerencia:         {s['sugerencia']}")
        if s.get("nota"):
            print(f"  Nota del usuario:   {s['nota']}")

        accion = preguntar("\n  ¿[a]probar, [e]ditar, [r]echazar, [s]altar, [q]salir? ", "aersq")
        if accion == "q":
            break
        if accion == "s":
            continue

        if accion in ("a", "e"):
            traduccion = s["sugerencia"]
            if accion == "e":
                editada = input(f"  Traducción final [{traduccion}]: ").strip()
                traduccion = editada or traduccion
            agregar_al_diccionario(diccionario, s["direccion"], s["original"], traduccion)
            inversa = preguntar(f"  ¿Agregar también {NOMBRES[dest]} → {NOMBRES[src]}? [s/n] ", "sn")
            if inversa == "s":
                agregar_al_diccionario(diccionario, f"{dest}-{src}", traduccion, s["original"])
            s["estado"], s["traduccion_aprobada"] = "aprobada", traduccion
            aprobadas += 1
            print("  ✓ Agregada al diccionario verificado.")
        else:
            s["estado"] = "rechazada"
            print("  ✗ Rechazada.")

        s["revisada"] = datetime.now().isoformat(timespec="seconds")
        revisadas.append(s)
        procesadas.add(s["id"])

    if aprobadas:
        guardar(RUTA_DICCIONARIO, diccionario)
    if procesadas:
        guardar(RUTA_REVISADAS, revisadas)
        # Se vuelve a leer el archivo justo antes de guardar, por si llegaron
        # sugerencias nuevas desde la app mientras revisabas.
        actuales = leer(RUTA_PENDIENTES, [])
        guardar(RUTA_PENDIENTES, [x for x in actuales if x["id"] not in procesadas])

    print("─" * 60)
    print(f"Listo: {aprobadas} aprobada(s), {len(procesadas) - aprobadas} rechazada(s), "
          f"{len(pendientes) - len(procesadas)} pendiente(s).")


if __name__ == "__main__":
    main()
