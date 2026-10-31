// Lectura en voz alta que también funciona en iPhone y iPad (Safari).
//
// Safari en iOS tiene tres manías con speechSynthesis:
//  1. No suena hasta que se "desbloquea" desde un toque del usuario.
//  2. A veces nunca avisa que terminó de hablar (no dispara onend), o
//     pierde la lectura si nadie guarda una referencia a ella.
//  3. Si se cancela una lectura y se habla otra en el mismo instante,
//     la nueva se queda muda.
// Este módulo resuelve las tres. No existe voz en maya en ningún
// navegador, así que se usa una voz en español como aproximación.

export const ES_IOS =
  typeof navigator !== 'undefined' &&
  (/iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1));

const lecturasVivas = new Set<SpeechSynthesisUtterance>(); // evita que Safari las descarte
let desbloqueada = false;

function hayVoz() {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

function vozEnEspanol(): SpeechSynthesisVoice | undefined {
  const voces = window.speechSynthesis.getVoices();
  const de = (prefijo: string) => voces.find((v) => v.lang.replace('_', '-').toLowerCase().startsWith(prefijo));
  return de('es-mx') || de('es-us') || de('es-419') || de('es');
}

// Llamar SIEMPRE dentro del manejador de un toque o clic del usuario,
// antes de cualquier await, para que Safari permita hablar después.
export function desbloquearVoz() {
  if (desbloqueada || !hayVoz()) return;
  desbloqueada = true;
  const silencio = new SpeechSynthesisUtterance(' ');
  silencio.volume = 0;
  window.speechSynthesis.speak(silencio);
}

type Opciones = { velocidad?: number; interrumpir?: boolean; alTerminar?: () => void };

// Lee el texto en voz alta. Devuelve false si el navegador no puede hablar.
// alTerminar se llama SIEMPRE una sola vez: cuando termina, si falla, o
// por un vigilante de tiempo si Safari nunca avisa.
export function hablar(texto: string, { velocidad = 0.95, interrumpir = false, alTerminar }: Opciones = {}): boolean {
  if (!hayVoz() || !texto.trim()) return false;
  const voz = window.speechSynthesis;

  const lectura = new SpeechSynthesisUtterance(texto);
  const elegida = vozEnEspanol();
  lectura.lang = elegida?.lang || 'es-MX';
  if (elegida) lectura.voice = elegida;
  lectura.rate = velocidad;
  lecturasVivas.add(lectura);

  let terminada = false;
  const terminar = () => {
    if (terminada) return;
    terminada = true;
    lecturasVivas.delete(lectura);
    window.clearTimeout(vigilante);
    alTerminar?.();
  };
  lectura.onend = terminar;
  lectura.onerror = terminar;
  // Tiempo estimado de la lectura más un margen; si Safari no avisa, se da por terminada.
  const vigilante = window.setTimeout(terminar, 2500 + (texto.length * 90) / velocidad);

  const empezar = () => {
    if (voz.paused) voz.resume(); // Safari a veces queda en pausa sin razón
    voz.speak(lectura);
  };
  if (interrumpir && (voz.speaking || voz.pending)) {
    voz.cancel();
    window.setTimeout(empezar, 80); // en iOS, hablar justo después de cancelar se queda mudo
  } else {
    empezar();
  }
  return true;
}

export function callar() {
  if (hayVoz()) window.speechSynthesis.cancel();
}
