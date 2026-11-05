// Comunicación con el backend (Flask). Todas las llamadas pasan por aquí
// para que el manejo de errores sea igual en toda la app: si el backend
// responde con { error: "..." } (por ejemplo, un límite de uso), ese
// mensaje es el que se muestra al usuario.

// Dirección del backend:
//  - En producción (Render) se define VITE_API_URL con la URL del backend.
//  - En desarrollo, si no hay VITE_API_URL, se usa la misma dirección con la
//    que se abrió la página, en el puerto 8001. Así funciona igual en
//    localhost y desde el celular en cualquier red WiFi, sin tener que
//    actualizar una IP fija cada vez que cambia la red.
function direccionPorDefecto() {
  if (typeof window === 'undefined') return 'http://127.0.0.1:8001';
  return `${window.location.protocol}//${window.location.hostname}:8001`;
}

export const API_URL: string = import.meta.env.VITE_API_URL || direccionPorDefecto();

async function pedir<T>(ruta: string, opciones: RequestInit, mensajeError: string): Promise<T> {
  let respuesta: Response;
  try {
    respuesta = await fetch(`${API_URL}${ruta}`, opciones);
  } catch {
    throw new Error('No se pudo conectar con el servidor. Revisa tu conexión.');
  }
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(datos.error || mensajeError);
  return datos as T;
}

export function postJSON<T = any>(ruta: string, cuerpo: unknown, mensajeError = 'Algo salió mal. Intenta de nuevo.'): Promise<T> {
  return pedir<T>(ruta, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cuerpo),
  }, mensajeError);
}

export function getJSON<T = any>(ruta: string, mensajeError = 'Algo salió mal. Intenta de nuevo.'): Promise<T> {
  return pedir<T>(ruta, { method: 'GET' }, mensajeError);
}