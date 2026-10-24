"""
Revisa y borra traducciones guardadas en la caché (datos.db).

La caché guarda las traducciones automáticas para no volver a pagarlas.
Si alguna quedó mal (por ejemplo, "hola" → "Hello"), se sigue usando
hasta que la borres. Desde la carpeta backend/:

    python limpiar_cache.py               ver cuántas hay y las últimas
    python limpiar_cache.py hola          ver y borrar las que contienen "hola"
    python limpiar_cache.py --todo        borrar toda la caché

Borrar no rompe nada: si alguien vuelve a pedir esa frase, se traduce de
nuevo con Azure y se guarda la versión nueva.
"""

import sys

import almacen

DIRECCION = {("es", "yua"): "español → maya", ("yua", "es"): "maya → español"}


def mostrar(entradas):
    for src, dest, clave, resultado, creado in entradas:
        print(f"  [{DIRECCION.get((src, dest), f'{src}→{dest}')}]  {clave!r} → {resultado!r}   ({creado})")


def confirmar(pregunta: str) -> bool:
    return input(f"{pregunta} [s/n] ").strip().lower() == "s"


def main():
    almacen.inicializar()
    argumentos = sys.argv[1:]

    if argumentos == ["--todo"]:
        total = len(almacen.cache_buscar())
        if total and confirmar(f"¿Borrar las {total} traducciones de la caché?"):
            print(f"✓ {almacen.cache_borrar()} borradas.")
        elif not total:
            print("La caché ya está vacía.")
        return

    if not argumentos:
        entradas = almacen.cache_buscar()
        print(f"La caché tiene {len(entradas)} traducciones. Las 20 más recientes:")
        mostrar(entradas[-20:])
        print("\nPara borrar alguna: python limpiar_cache.py <texto>   ·   todas: python limpiar_cache.py --todo")
        return

    texto = " ".join(argumentos).lower()
    entradas = almacen.cache_buscar(texto)
    if not entradas:
        print(f"No hay traducciones en caché que contengan {texto!r}.")
        return
    print(f"Encontré {len(entradas)}:")
    mostrar(entradas)
    if confirmar("¿Borrarlas?"):
        print(f"✓ {almacen.cache_borrar(entradas)} borradas.")


if __name__ == "__main__":
    main()