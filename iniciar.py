"""
Levanta el backend (Flask, en backend/) y el frontend (React, en frontend/)
juntos con un solo comando.

Uso:
    python iniciar.py

Requisitos previos (una sola vez):
    1) Entorno virtual de Python creado y activado, con:
           pip install -r backend/requirements.txt
    2) Dependencias de Node instaladas:
           cd frontend
           npm install --legacy-peer-deps
           cd ..

Para detener todo: Ctrl+C en esta misma terminal.
"""

import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).parent
BACKEND = RAIZ / "backend"
FRONTEND = RAIZ / "frontend"

URL_FRONTEND = "http://localhost:8080"


def comando_npm():
    """Usa npm.cmd en Windows, npm en todo lo demás."""
    npm = shutil.which("npm")
    if npm:
        return [npm, "run", "dev"]
    bun = shutil.which("bun")
    if bun:
        return [bun, "run", "dev"]
    sys.exit(
        "No encontré 'npm' ni 'bun' en el PATH. Instala Node.js "
        "(https://nodejs.org) y vuelve a intentar."
    )


def main():
    print("Iniciando backend (Flask) en http://127.0.0.1:8001 ...")
    proceso_backend = subprocess.Popen(
        [sys.executable, "tranlate.py"],
        cwd=BACKEND,
    )

    print("Iniciando frontend (React) ...")
    proceso_frontend = subprocess.Popen(
        comando_npm(),
        cwd=FRONTEND,
        shell=(sys.platform == "win32"),
    )

    time.sleep(3)  # da tiempo a que el servidor de desarrollo levante
    try:
        webbrowser.open(URL_FRONTEND)
    except Exception:
        pass

    print(f"\nListo. Abre {URL_FRONTEND} si no se abrió solo.")
    print("Presiona Ctrl+C aquí para detener ambos servidores.\n")

    try:
        proceso_backend.wait()
        proceso_frontend.wait()
    except KeyboardInterrupt:
        print("\nDeteniendo...")
        proceso_backend.terminate()
        proceso_frontend.terminate()


if __name__ == "__main__":
    main()