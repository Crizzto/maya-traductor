# Traductor Maya Yucateco

Proyecto unificado: backend en Flask (`backend/`) + frontend en React/TanStack
(`frontend/`, generado con Lovable).

## Estructura

```
traductor-maya/
├── backend/
│   ├── tranlate.py            # servidor Flask + endpoint /api/traducir
│   ├── diccionario.json       # tu diccionario verificado a mano
│   ├── diccionario_colonial.json  # glosario sacado de vocabularios históricos
│   └── requirements.txt
├── frontend/                  # app de React (Lovable)
└── iniciar.py                 # levanta backend + frontend juntos
```

## Instalación (una sola vez)

1. Crea y activa un entorno virtual de Python en la raíz del proyecto o
   donde prefieras:
   ```
   python -m venv .venv
   .venv\Scripts\Activate.ps1      # Windows PowerShell
   ```
2. Instala las dependencias de Python:
   ```
   pip install -r backend/requirements.txt
   ```
3. Instala las dependencias de Node (requiere Node.js instalado):
   ```
   cd frontend
   npm install --legacy-peer-deps
   cd ..
   ```
   (El `--legacy-peer-deps` evita un bug conocido de npm con este
   proyecto; si usas `bun`, basta con `bun install` normal.)

## Uso diario

Con el entorno virtual activado, desde la carpeta `traductor-maya/`:

```
python iniciar.py
```

Esto levanta el backend Flask (`http://127.0.0.1:8001`) y el frontend de
React (`http://localhost:3000`) al mismo tiempo, y abre el navegador
automáticamente. Para detener todo, `Ctrl+C` en esa misma terminal.

## Notas

- El diccionario local (`diccionario.json`) se revisa primero en cada
  traducción; agrégale palabras verificadas para depender menos de la
  red.
- `diccionario_colonial.json` usa ortografía histórica/colonial del
  maya, distinta a la moderna — las traducciones que vienen de ahí se
  marcan como tales en el resultado.
- Si Google Translate responde con error 429 (demasiadas peticiones),
  espera unos minutos antes de volver a intentar.
