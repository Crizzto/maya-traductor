// Comunicación con el backend (Flask). Todas las llamadas pasan por aquí
// para que el manejo de errores sea igual en toda la app: si el backend
// responde con { error: "..." } (por ejemplo, un límite de uso), ese
// mensaje es el que se muestra al usuario.

// En desarrollo el backend corre en 127.0.0.1:8001; al desplegar, define
// VITE_API_URL con la URL real del backend.
export const API_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8001';

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
