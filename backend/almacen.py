"""
Almacenamiento persistente en SQLite (un solo archivo, sin servidor).

Guarda dos cosas que antes vivían en memoria y se perdían al reiniciar:
  - La caché de traducciones automáticas (ahorra cuota de Azure).
  - El consumo por mes de cada servicio (caracteres de Azure Translator,
    peticiones a Gemini, sesiones de voz), para saber cuánto llevas del
    mes y poder frenar antes de pasarte de la capa gratuita.

El archivo es backend/datos.db por defecto; se puede cambiar con la
variable de entorno DB_PATH.
"""

import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("tranlate")

RUTA_DB = Path(os.environ.get("DB_PATH", Path(__file__).parent / "datos.db"))
_candado = threading.Lock()


def _conectar() -> sqlite3.Connection:
    conexion = sqlite3.connect(RUTA_DB, timeout=10)
    conexion.execute("PRAGMA journal_mode=WAL")  # lecturas y escrituras simultáneas sin bloquearse
    return conexion


def inicializar() -> None:
    with _candado, _conectar() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                src TEXT NOT NULL,
                dest TEXT NOT NULL,
                clave TEXT NOT NULL,
                resultado TEXT NOT NULL,
                creado TEXT NOT NULL,
                PRIMARY KEY (src, dest, clave)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS uso (
                periodo TEXT NOT NULL,      -- '2026-10' (mes) o '2026-10-22' (día)
                servicio TEXT NOT NULL,
                cantidad INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (periodo, servicio)
            )
        """)
    logger.info("[DB] Base de datos lista en %s", RUTA_DB)


# --- Caché de traducciones ---

def cache_obtener(src: str, dest: str, clave: str) -> str | None:
    with _conectar() as db:
        fila = db.execute(
            "SELECT resultado FROM cache WHERE src=? AND dest=? AND clave=?",
            (src, dest, clave),
        ).fetchone()
    return fila[0] if fila else None


def cache_guardar(src: str, dest: str, clave: str, resultado: str) -> None:
    with _candado, _conectar() as db:
        db.execute(
            "INSERT OR REPLACE INTO cache (src, dest, clave, resultado, creado) VALUES (?, ?, ?, ?, ?)",
            (src, dest, clave, resultado, datetime.now().isoformat(timespec="seconds")),
        )


def cache_buscar(texto: str = "") -> list[tuple]:
    """Entradas de la caché que contienen el texto (todas si va vacío)."""
    with _conectar() as db:
        return db.execute(
            "SELECT src, dest, clave, resultado, creado FROM cache WHERE clave LIKE ? OR resultado LIKE ? ORDER BY creado",
            (f"%{texto}%", f"%{texto}%"),
        ).fetchall()


def cache_borrar(entradas: list[tuple] | None = None) -> int:
    """Borra las entradas indicadas (src, dest, clave) o toda la caché."""
    with _candado, _conectar() as db:
        if entradas is None:
            return db.execute("DELETE FROM cache").rowcount
        return sum(
            db.execute("DELETE FROM cache WHERE src=? AND dest=? AND clave=?", e[:3]).rowcount
            for e in entradas
        )


# --- Consumo por servicio ---

def mes_actual() -> str:
    return datetime.now().strftime("%Y-%m")


def dia_actual() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def uso_sumar(servicio: str, cantidad: int, periodo: str | None = None) -> int:
    """Suma al contador del periodo (mes actual por defecto) y devuelve el total."""
    periodo = periodo or mes_actual()
    with _candado, _conectar() as db:
        db.execute(
            """
            INSERT INTO uso (periodo, servicio, cantidad) VALUES (?, ?, ?)
            ON CONFLICT (periodo, servicio) DO UPDATE SET cantidad = cantidad + excluded.cantidad
            """,
            (periodo, servicio, cantidad),
        )
        return db.execute(
            "SELECT cantidad FROM uso WHERE periodo=? AND servicio=?", (periodo, servicio)
        ).fetchone()[0]


def uso_obtener(servicio: str, periodo: str | None = None) -> int:
    periodo = periodo or mes_actual()
    with _conectar() as db:
        fila = db.execute(
            "SELECT cantidad FROM uso WHERE periodo=? AND servicio=?", (periodo, servicio)
        ).fetchone()
    return fila[0] if fila else 0


def resumen_uso() -> dict:
    """Consumo del mes y del día actuales, para mostrar en la ruta de estado."""
    mes, dia = mes_actual(), dia_actual()
    with _conectar() as db:
        filas = db.execute(
            "SELECT periodo, servicio, cantidad FROM uso WHERE periodo IN (?, ?)", (mes, dia)
        ).fetchall()
        entradas_cache = db.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    resumen = {"mes": {}, "hoy": {}, "traducciones_en_cache": entradas_cache}
    for periodo, servicio, cantidad in filas:
        resumen["mes" if periodo == mes else "hoy"][servicio] = cantidad
    return resumen