// Lectura en voz alta de las traducciones.
//
// En iPhone y iPad (todos sus navegadores usan el motor de Safari), la voz
// del navegador (speechSynthesis) no es confiable: el interruptor de
// silencio la apaga, en algunos navegadores no suena y con el micrófono
// abierto sale por la bocina del oído. Por eso, en iOS, la voz se genera en
// el servidor con Azure (/api/voz/hablar) y se reproduce como un audio
// normal, que suena por el altavoz aunque el teléfono esté en silencio.
// En los demás equipos se usa la voz del navegador. Si una de las dos
// falla, se intenta con la otra.
//
// No existe voz en maya: se usa una voz en español como aproximación.
import { API_URL } from '@/lib/api';

export const ES_IOS =
  typeof navigator !== 'undefined' &&
  (/iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1));

// MP3 de silencio, mínimo, para "desbloquear" el reproductor en iOS.
const SILENCIO = 'data:audio/mpeg;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQxAADB8AhSmxhIIEVCSiJrDCQBTcu3UrAIwUdkRgQbFAZC1CQEwTJ9mjRvBA4UOLD8nKVOWfh+UlK3z/177OXrfOdKl7pyn3Xf//WreyTRUoAWgBgkOAGbZHBgG1OF6zM82DWbZaUmMBptgQhGjsyYqc9ae9XFz280948NMBWInljyzsNRFLPWdnZGWrddDsjK1unuSrVN9jJsK8KuQtQCtMBjCEtImISdNKJOopIpBFpNSMbIHCSRpRR5iakjTiyzLhchUUBwCgyKiweBv/7UsQbg8isVNoMPMjAAAA0gAAABEVFGmgqK////9bP/6XCykxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq';

let reproductor: HTMLAudioElement | null = null;
let urlActual = '';
let desbloqueada = false;
let servidorNoDisponible = false; // si el backend no tiene voz, no se insiste
const lecturasVivas = new Set<SpeechSynthesisUtterance>(); // evita que Safari las descarte

function hayVozNavegador() {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

function obtenerReproductor() {
  if (!reproductor) {
    reproductor = new Audio();
    reproductor.preload = 'auto';
    reproductor.setAttribute('playsinline', '');
  }
  return reproductor;
}

function vozEnEspanol(): SpeechSynthesisVoice | undefined {
  const voces = window.speechSynthesis.getVoices();
  const de = (prefijo: string) => voces.find((v) => v.lang.replace('_', '-').toLowerCase().startsWith(prefijo));
  return de('es-mx') || de('es-us') || de('es-419') || de('es');
}

// Llamar SIEMPRE dentro del manejador de un toque o clic del usuario, antes
// de cualquier await: iOS solo deja sonar audio que se "desbloqueó" así.
export function desbloquearVoz() {
  if (desbloqueada || typeof window === 'undefined') return;
  desbloqueada = true;
  const audio = obtenerReproductor();
  audio.src = SILENCIO;
  audio.play().catch(() => { /* sin sonido aún: se intentará al hablar */ });
  if (hayVozNavegador()) {
    const silencio = new SpeechSynthesisUtterance(' ');
    silencio.volume = 0;
    window.speechSynthesis.speak(silencio);
  }
}

type Opciones = { velocidad?: number; interrumpir?: boolean; alTerminar?: () => void };

function hablarConNavegador(texto: string, velocidad: number, interrumpir: boolean, terminar: () => void): boolean {
  if (!hayVozNavegador()) return false;
  const voz = window.speechSynthesis;
  const lectura = new SpeechSynthesisUtterance(texto);
  const elegida = vozEnEspanol();
  lectura.lang = elegida?.lang || 'es-MX';
  if (elegida) lectura.voice = elegida;
  lectura.rate = velocidad;
  lecturasVivas.add(lectura);
  const fin = () => { lecturasVivas.delete(lectura); terminar(); };
  lectura.onend = fin;
  lectura.onerror = fin;
  const empezar = () => {
    if (voz.paused) voz.resume(); // Safari a veces queda en pausa sin razón
    voz.speak(lectura);
  };
  if (interrumpir && (voz.speaking || voz.pending)) {
    voz.cancel();
    window.setTimeout(empezar, 80); // hablar justo después de cancelar se queda mudo en iOS
  } else {
    empezar();
  }
  return true;
}

async function hablarConServidor(texto: string, terminar: () => void, siFalla: () => void) {
  try {
    const respuesta = await fetch(`${API_URL}/api/voz/hablar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texto }),
    });
    if (respuesta.status === 503) servidorNoDisponible = true;
    if (!respuesta.ok) throw new Error(`voz del servidor: ${respuesta.status}`);
    const audio = obtenerReproductor();
    if (urlActual) URL.revokeObjectURL(urlActual);
    urlActual = URL.createObjectURL(await respuesta.blob());
    audio.onended = terminar;
    audio.onerror = siFalla;
    audio.src = urlActual;
    await audio.play();
  } catch (e) {
    console.warn('[Voz] No se pudo usar la voz del servidor; se usa la del navegador.', e);
    siFalla();
  }
}

// Lee el texto en voz alta. Devuelve false si no hay forma de hablar.
// alTerminar se llama SIEMPRE una sola vez: cuando termina, si falla, o
// por un vigilante de tiempo si el navegador nunca avisa.
export function hablar(texto: string, { velocidad = 0.95, interrumpir = false, alTerminar }: Opciones = {}): boolean {
  if (!texto.trim() || typeof window === 'undefined') return false;

  let terminada = false;
  const terminar = () => {
    if (terminada) return;
    terminada = true;
    window.clearTimeout(vigilante);
    alTerminar?.();
  };
  // Tiempo estimado (con margen para descargar el audio); si nadie avisa, se da por terminada.
  const vigilante = window.setTimeout(terminar, 6000 + (texto.length * 90) / velocidad);

  if (interrumpir) callar();

  if (ES_IOS && !servidorNoDisponible) {
    hablarConServidor(texto, terminar, () => {
      if (!hablarConNavegador(texto, velocidad, false, terminar)) terminar();
    });
    return true;
  }
  if (hablarConNavegador(texto, velocidad, interrumpir, terminar)) return true;
  if (!servidorNoDisponible) {
    hablarConServidor(texto, terminar, terminar);
    return true;
  }
  window.clearTimeout(vigilante);
  return false;
}

export function callar() {
  if (reproductor && !reproductor.paused) reproductor.pause();
  if (hayVozNavegador()) window.speechSynthesis.cancel();
}
