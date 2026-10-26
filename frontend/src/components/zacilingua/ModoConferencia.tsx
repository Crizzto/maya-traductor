// Modo conferencia: escucha español por el micrófono, muestra en vivo lo
// que va entendiendo y traduce cada frase al maya en voz alta.
// Usa Azure Speech (cualquier navegador) y, si no está configurado, el
// reconocedor integrado del navegador (solo Chrome/Edge) como respaldo.
import { useEffect, useRef, useState } from 'react';
import { Mic, MicOff, Volume2, VolumeX } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getJSON, postJSON } from '@/lib/api';
import { tx, useT } from '@/lib/preferencias';

// Límites de uso: cada minuto con el micrófono abierto gasta de la cuota
// gratuita de Azure Speech (5 horas al mes), aunque nadie hable.
const INACTIVIDAD_S = 60;        // sin voz durante 1 minuto → se apaga
const AVISO_S = 15;              // los últimos 15 s se muestra una cuenta atrás
const DURACION_MAXIMA_S = 20 * 60; // ninguna sesión dura más de 20 minutos
const OCULTA_MAXIMO_S = 30;      // si el usuario sale de la página 30 s → se apaga

function minutos(segundos: number) {
  const s = Math.max(0, Math.floor(segundos));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function ModoConferencia({ onNotice: setNotice }: { onNotice: (mensaje: string) => void }) {
  const t = useT();
  const [escuchando, setEscuchando] = useState(false);
  const [estadoMic, setEstadoMic] = useState<'apagado' | 'escuchando' | 'detectando'>('apagado');
  const [transcripcion, setTranscripcion] = useState<{ original: string; traducido: string }[]>([]);
  // Panel en vivo del modo conferencia: lo que el reconocedor va oyendo
  // (texto provisional) y la última frase completa con su traducción.
  const [textoEnVivo, setTextoEnVivo] = useState('');
  // Diagnóstico visible del reconocedor: qué eventos han llegado y cuál fue
  // el último error, para saber en qué paso se corta.
  const [diagnostico, setDiagnostico] = useState({ inicio: false, audio: false, sonido: false, voz: false, resultado: false, error: '', reinicios: 0 });
  // Motor de voz en uso: Azure Speech (cualquier navegador) o el
  // reconocedor integrado del navegador (solo Chrome/Edge) como respaldo.
  const [motorVoz, setMotorVoz] = useState<'azure' | 'navegador' | null>(null);
  const azureVozRef = useRef<{ reconocedor: any; renovar: number } | null>(null);
  const marcar = (cambio: Partial<typeof diagnostico>) => {
    if (cambio.sonido || cambio.voz || cambio.resultado) registrarActividad();
    setDiagnostico((previo) => ({ ...previo, ...cambio }));
  };

  // Control de límites (ver constantes arriba).
  const ultimaActividadRef = useRef(0);
  const inicioSesionRef = useRef(0);
  const ocultaDesdeRef = useRef<number | null>(null);
  const [avisoInactividad, setAvisoInactividad] = useState<number | null>(null);
  const [segundosSesion, setSegundosSesion] = useState(0);

  function registrarActividad() {
    ultimaActividadRef.current = Date.now();
  }

  function seguirEscuchando() {
    registrarActividad();
    setAvisoInactividad(null);
  }

  useEffect(() => {
    if (!escuchando) {
      setAvisoInactividad(null);
      setSegundosSesion(0);
      return;
    }
    const revisar = window.setInterval(() => {
      const ahora = Date.now();
      // Mientras la app lee una traducción también cuenta como actividad.
      if (lecturasPendientesRef.current > 0) ultimaActividadRef.current = ahora;

      const restante = INACTIVIDAD_S - (ahora - ultimaActividadRef.current) / 1000;
      if (restante <= 0) {
        detenerModoConferencia();
        setNotice(t('Micrófono apagado por inactividad: no se detectó voz durante 1 minuto.'));
        return;
      }
      setAvisoInactividad(restante <= AVISO_S ? Math.ceil(restante) : null);

      const sesion = (ahora - inicioSesionRef.current) / 1000;
      setSegundosSesion(sesion);
      if (sesion >= DURACION_MAXIMA_S) {
        detenerModoConferencia();
        setNotice(t('Sesión terminada: el modo conferencia se apaga solo a los 20 minutos. Puedes volver a encenderlo.'));
        return;
      }

      if (document.hidden) {
        ocultaDesdeRef.current ??= ahora;
        if ((ahora - ocultaDesdeRef.current) / 1000 >= OCULTA_MAXIMO_S) {
          detenerModoConferencia();
          setNotice(t('Micrófono apagado porque saliste de la página.'));
        }
      } else {
        ocultaDesdeRef.current = null;
      }
    }, 1000);
    return () => window.clearInterval(revisar);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [escuchando]);
  const [ultimaFrase, setUltimaFrase] = useState<{ original: string; traducido: string | null } | null>(null);
  const barraNivelRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<{ stream: MediaStream; contexto: AudioContext; frame: number } | null>(null);
  const reconocimientoRef = useRef<any>(null);
  const escuchandoRef = useRef(false); // espejo de 'escuchando' para leer el valor actual dentro de callbacks async

  // Anti-eco: mientras la app lee una traducción en voz alta (y un momento
  // después), el micrófono capta esa misma voz. Lo que se oiga en ese lapso
  // se ignora, y también cualquier frase que repita lo último que se leyó.
  const [leerEnVoz, setLeerEnVoz] = useState(true);
  const leerEnVozRef = useRef(true);
  const [hablando, setHablando] = useState(false);
  const lecturasPendientesRef = useRef(0);
  const ignorarHastaRef = useRef(0);
  const ultimoLeidoRef = useRef('');

  function microfonoEnPausa() {
    return lecturasPendientesRef.current > 0 || Date.now() < ignorarHastaRef.current;
  }

  function palabras(texto: string) {
    return texto.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9ñ'’ ]/g, ' ').split(/\s+/).filter(Boolean);
  }

  function esEco(texto: string) {
    // Si casi todas las palabras de lo que se oyó estaban en lo último que
    // leyó la app, es su propia voz y no alguien hablando.
    const oidas = palabras(texto);
    if (!oidas.length || !ultimoLeidoRef.current) return false;
    const leidas = new Set(palabras(ultimoLeidoRef.current));
    const coinciden = oidas.filter((p) => leidas.has(p)).length;
    return coinciden / oidas.length >= 0.6;
  }

  function leerEnVozAlta(texto: string) {
    if (!leerEnVozRef.current || !('speechSynthesis' in window)) return;
    const lectura = new SpeechSynthesisUtterance(texto);
    lectura.lang = 'es-MX';
    lectura.rate = 0.95;
    ultimoLeidoRef.current = texto;
    lecturasPendientesRef.current += 1;
    setHablando(true);
    const terminar = () => {
      lecturasPendientesRef.current = Math.max(0, lecturasPendientesRef.current - 1);
      if (lecturasPendientesRef.current === 0) {
        // Margen extra: el eco de la habitación llega un instante después.
        ignorarHastaRef.current = Date.now() + 900;
        setHablando(false);
      }
    };
    lectura.onend = terminar;
    lectura.onerror = terminar;
    window.speechSynthesis.speak(lectura);
  }

  function cambiarLecturaEnVoz() {
    const nuevo = !leerEnVozRef.current;
    leerEnVozRef.current = nuevo;
    setLeerEnVoz(nuevo);
    if (!nuevo && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      lecturasPendientesRef.current = 0;
      setHablando(false);
    }
  }

  function ignorarSiEsEco(texto: string, motor: string) {
    if (microfonoEnPausa() || esEco(texto)) {
      console.log(`[Modo conferencia · ${motor}] Ignorado (es la voz de la app):`, texto);
      setTextoEnVivo('');
      return true;
    }
    return false;
  }

  async function traducirYHablar(fraseOriginal: string) {
    // Igual que traducir(), pero para el modo conferencia: no toca el
    // cuadro de texto principal, traduce directo y lee el resultado solo.
    setUltimaFrase({ original: fraseOriginal, traducido: null });
    try {
      const datos = await postJSON<{ resultado: string }>('/api/traducir', { texto: fraseOriginal, direccion: 'spanish-maya' });
      setUltimaFrase({ original: fraseOriginal, traducido: datos.resultado });
      setTranscripcion((previa) => [...previa, { original: fraseOriginal, traducido: datos.resultado }].slice(-20));
      leerEnVozAlta(datos.resultado);
    } catch (error) {
      console.error('[Modo conferencia] Falló la traducción:', error);
      setUltimaFrase({ original: fraseOriginal, traducido: `⚠ ${t('No se pudo traducir esta frase.')}` });
      setTranscripcion((previa) => [...previa, { original: fraseOriginal, traducido: `⚠ ${t('No se pudo traducir esta frase.')}` }].slice(-20));
    }
  }

  async function iniciarModoConferencia() {
    // El micrófono SOLO funciona en "contexto seguro": HTTPS, o localhost
    // exactamente. Si entras por la IP de tu red local en HTTP (ej.
    // http://192.168.x.x:8080), el navegador lo bloquea sin avisar.
    if (!window.isSecureContext) {
      setNotice(t('El micrófono solo funciona en páginas seguras (HTTPS) o en «localhost»; no funciona entrando por la IP de la red local.'));
      console.error('[Modo conferencia] Contexto no seguro (isSecureContext=false). El micrófono no va a funcionar aquí.');
      return;
    }
    setDiagnostico({ inicio: false, audio: false, sonido: false, voz: false, resultado: false, error: '', reinicios: 0 });
    setUltimaFrase(null);
    ultimaActividadRef.current = Date.now();
    inicioSesionRef.current = Date.now();
    ocultaDesdeRef.current = null;
    escuchandoRef.current = true;
    setEscuchando(true);

    if (await iniciarAzureSpeech()) return;
    if (!escuchandoRef.current) return; // lo detuvieron mientras se conectaba
    iniciarReconocedorNavegador();
  }

  async function pedirTokenVoz(): Promise<{ token: string; region: string }> {
    return getJSON('/api/voz/token', 'No se pudo obtener el token de voz.');
  }

  async function iniciarAzureSpeech(): Promise<boolean> {
    // Devuelve true si Azure Speech arrancó; false para usar el respaldo.
    let credenciales;
    try {
      credenciales = await pedirTokenVoz();
    } catch (e) {
      console.warn('[Modo conferencia] Azure Speech no disponible, uso el reconocedor del navegador:', e);
      return false;
    }
    if (!escuchandoRef.current) return true;

    try {
      // Import dinámico: el SDK solo existe en el navegador, y así no pesa
      // en la carga inicial de la página.
      const sdk = await import('microsoft-cognitiveservices-speech-sdk');
      const configuracion = sdk.SpeechConfig.fromAuthorizationToken(credenciales.token, credenciales.region);
      configuracion.speechRecognitionLanguage = 'es-MX';
      const reconocedor = new sdk.SpeechRecognizer(configuracion, sdk.AudioConfig.fromDefaultMicrophoneInput());

      reconocedor.sessionStarted = () => {
        console.log('[Modo conferencia · Azure] Sesión iniciada.');
        marcar({ inicio: true, audio: true });
        setEstadoMic('escuchando');
        if (!audioRef.current) iniciarMedidorDeVolumen();
      };
      reconocedor.speechStartDetected = () => {
        marcar({ sonido: true });
        setEstadoMic('detectando');
      };
      reconocedor.speechEndDetected = () => setEstadoMic('escuchando');
      reconocedor.recognizing = (_r: unknown, evento: any) => {
        if (microfonoEnPausa()) return; // no mostrar la voz de la app como texto en vivo
        marcar({ voz: true });
        setEstadoMic('detectando');
        setTextoEnVivo(evento.result.text);
      };
      reconocedor.recognized = (_r: unknown, evento: any) => {
        setEstadoMic('escuchando');
        setTextoEnVivo('');
        const texto = (evento.result.text || '').trim();
        if (evento.result.reason === sdk.ResultReason.RecognizedSpeech && texto) {
          if (ignorarSiEsEco(texto, 'Azure')) return;
          console.log('[Modo conferencia · Azure] Reconocido:', texto);
          marcar({ resultado: true, error: '' });
          traducirYHablar(texto);
        }
      };
      reconocedor.canceled = (_r: unknown, evento: any) => {
        if (evento.reason !== sdk.CancellationReason.Error) return;
        console.error('[Modo conferencia · Azure] Cancelado:', evento.errorCode, evento.errorDetails);
        marcar({ error: `azure ${evento.errorCode}` });
        setNotice(
          evento.errorCode === sdk.CancellationErrorCode.AuthenticationFailure
            ? t('Azure Speech rechazó la clave. Revisa AZURE_SPEECH_KEY y AZURE_SPEECH_REGION en el backend.')
            : evento.errorCode === sdk.CancellationErrorCode.TooManyRequests
              ? t('Se alcanzó el límite de Azure Speech (5 horas gratis al mes o demasiadas sesiones a la vez).')
              : t('Se perdió la conexión con Azure Speech. Revisa tu internet e inténtalo de nuevo.')
        );
        detenerModoConferencia();
      };

      // El token dura 10 minutos: se renueva cada 9 para charlas largas.
      const renovar = window.setInterval(async () => {
        try { reconocedor.authorizationToken = (await pedirTokenVoz()).token; }
        catch (e) { console.warn('[Modo conferencia · Azure] No se pudo renovar el token:', e); }
      }, 9 * 60 * 1000);

      azureVozRef.current = { reconocedor, renovar };
      setMotorVoz('azure');
      await new Promise<void>((resolver, rechazar) => reconocedor.startContinuousRecognitionAsync(resolver, rechazar));
      console.log('[Modo conferencia · Azure] Reconocimiento continuo en marcha.');
      return true;
    } catch (e) {
      console.error('[Modo conferencia · Azure] No se pudo iniciar:', e);
      cerrarAzureSpeech();
      const mensaje = String(e);
      if (/Permission|NotAllowed|denied/i.test(mensaje)) {
        setNotice(t('Permiso de micrófono denegado. Revisa los permisos del sitio en tu navegador y vuelve a intentar.'));
        detenerModoConferencia();
        return true; // no tiene caso intentar el respaldo sin permiso
      }
      return false;
    }
  }

  function cerrarAzureSpeech() {
    const azure = azureVozRef.current;
    if (!azure) return;
    azureVozRef.current = null;
    window.clearInterval(azure.renovar);
    try {
      azure.reconocedor.stopContinuousRecognitionAsync(
        () => azure.reconocedor.close(),
        () => azure.reconocedor.close(),
      );
    } catch { /* ya estaba cerrado */ }
  }

  function iniciarReconocedorNavegador() {
    const Reconocedor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!Reconocedor) {
      setNotice(t('Tu navegador no tiene reconocimiento de voz propio y Azure Speech no está configurado en el backend.'));
      detenerModoConferencia();
      return;
    }
    setMotorVoz('navegador');
    if (!audioRef.current) iniciarMedidorDeVolumen();

    const reconocimiento = new Reconocedor();
    reconocimiento.lang = 'es-MX';
    reconocimiento.continuous = true;
    // true = el navegador manda texto "provisional" mientras hablas, así
    // el panel en vivo se va llenando palabra por palabra.
    reconocimiento.interimResults = true;

    // Estos eventos existen específicamente para saber si el micrófono
    // está "vivo" y detectando algo, sin esperar a que termine una frase.
    reconocimiento.onstart = () => {
      console.log('[Modo conferencia] onstart: el reconocimiento arrancó de verdad.');
      marcar({ inicio: true });
      setEstadoMic('escuchando');
    };
    reconocimiento.onaudiostart = () => {
      console.log('[Modo conferencia] onaudiostart: ya está recibiendo audio del micrófono.');
      marcar({ audio: true });
    };
    reconocimiento.onsoundstart = () => {
      console.log('[Modo conferencia] onsoundstart: detectó sonido.');
      marcar({ sonido: true });
    };
    reconocimiento.onnomatch = () => {
      console.log('[Modo conferencia] onnomatch: oyó algo pero no lo pudo convertir en texto.');
      marcar({ error: 'nomatch' });
    };
    reconocimiento.onspeechstart = () => {
      console.log('[Modo conferencia] onspeechstart: ¡detectó tu voz!');
      marcar({ voz: true });
      setEstadoMic('detectando');
    };
    reconocimiento.onspeechend = () => {
      setEstadoMic('escuchando');
    };
    reconocimiento.onaudioend = () => {
      console.log('[Modo conferencia] onaudioend: dejó de recibir audio.');
    };

    reconocimiento.onresult = (evento: any) => {
      marcar({ resultado: true, error: '' });
      let provisional = '';
      for (let i = evento.resultIndex; i < evento.results.length; i++) {
        const resultado = evento.results[i];
        const texto = resultado[0].transcript.trim();
        if (resultado.isFinal) {
          if (!texto || ignorarSiEsEco(texto, 'navegador')) continue;
          console.log('[Modo conferencia] Reconocido:', texto);
          traducirYHablar(texto);
        } else if (!microfonoEnPausa()) {
          provisional += resultado[0].transcript;
        }
      }
      setTextoEnVivo(provisional.trim());
    };
    reconocimiento.onerror = (evento: any) => {
      console.error('[Modo conferencia] Error de reconocimiento:', evento.error, evento.message);
      marcar({ error: evento.error });
      if (evento.error === 'no-speech') return; // benigno: solo hubo silencio, se reintenta solo
      if (evento.error === 'not-allowed' || evento.error === 'service-not-allowed') {
        setNotice(t('Permiso de micrófono denegado. Revisa los permisos del sitio en tu navegador y vuelve a intentar.'));
        detenerModoConferencia();
      } else if (evento.error === 'audio-capture') {
        setNotice(t('No se detectó ningún micrófono en este dispositivo.'));
        detenerModoConferencia();
      } else if (evento.error === 'network') {
        setNotice(t('El reconocimiento de voz no pudo conectarse con su servidor. Si usas Brave, Opera u otro navegador que no sea Chrome o Edge, no está soportado.'));
      } else if (evento.error === 'language-not-supported') {
        setNotice(t('Tu navegador no tiene reconocimiento de voz para español de México.'));
        detenerModoConferencia();
      }
    };
    reconocimiento.onend = () => {
      console.log('[Modo conferencia] onend: se cortó la sesión de reconocimiento.');
      // El reconocimiento se corta solo tras una pausa; si seguimos en
      // modo conferencia, lo reinicia automáticamente.
      if (escuchandoRef.current) {
        setDiagnostico((previo) => ({ ...previo, reinicios: previo.reinicios + 1 }));
        try { reconocimiento.start(); } catch (e) { console.error('[Modo conferencia] No se pudo reiniciar:', e); }
      }
    };

    try {
      reconocimiento.start();
      reconocimientoRef.current = reconocimiento;
      console.log('[Modo conferencia] Pedido start() — esperando onstart...');
    } catch (e) {
      console.error('[Modo conferencia] No se pudo iniciar:', e);
      setNotice(t('No se pudo iniciar el reconocimiento de voz.'));
      detenerModoConferencia();
    }
  }

  async function iniciarMedidorDeVolumen() {
    // Barra de volumen independiente del reconocimiento: si se mueve, el
    // micrófono SÍ está captando audio (aunque el reconocedor no entienda).
    // En Android se omite porque abrir el micrófono dos veces a la vez
    // puede bloquear el reconocimiento de voz.
    if (/Android/i.test(navigator.userAgent) || !navigator.mediaDevices?.getUserMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const contexto = new AudioContext();
      const analizador = contexto.createAnalyser();
      analizador.fftSize = 512;
      contexto.createMediaStreamSource(stream).connect(analizador);
      const muestras = new Uint8Array(analizador.fftSize);
      const dibujar = () => {
        analizador.getByteTimeDomainData(muestras);
        let suma = 0;
        for (const m of muestras) suma += ((m - 128) / 128) ** 2;
        const nivel = Math.min(1, Math.sqrt(suma / muestras.length) * 4);
        if (barraNivelRef.current) barraNivelRef.current.style.width = `${Math.round(nivel * 100)}%`;
        if (audioRef.current) audioRef.current.frame = requestAnimationFrame(dibujar);
      };
      audioRef.current = { stream, contexto, frame: requestAnimationFrame(dibujar) };
    } catch (e) {
      console.warn('[Modo conferencia] No se pudo abrir el medidor de volumen:', e);
    }
  }

  function detenerMedidorDeVolumen() {
    const audio = audioRef.current;
    if (!audio) return;
    audioRef.current = null;
    cancelAnimationFrame(audio.frame);
    audio.stream.getTracks().forEach((pista) => pista.stop());
    audio.contexto.close().catch(() => { });
    if (barraNivelRef.current) barraNivelRef.current.style.width = '0%';
  }

  function detenerModoConferencia() {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    lecturasPendientesRef.current = 0;
    setHablando(false);
    escuchandoRef.current = false;
    setEscuchando(false);
    setEstadoMic('apagado');
    setTextoEnVivo('');
    reconocimientoRef.current?.stop();
    reconocimientoRef.current = null;
    cerrarAzureSpeech();
    detenerMedidorDeVolumen();
    setMotorVoz(null);
  }

  // Si se cierra la página con el micrófono encendido, lo apaga bien.
  useEffect(() => () => {
    escuchandoRef.current = false;
    reconocimientoRef.current?.stop();
    cerrarAzureSpeech();
    detenerMedidorDeVolumen();
  }, []);

  return (
    <section className="conference-section" aria-labelledby="conference-title" style={{ marginTop: 48, background: '#1a2e1f', color: '#f5f2ec', borderRadius: 24, padding: 'clamp(20px, 5vw, 40px)' }}>
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 24, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 300px', minWidth: 0, display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
          <h3 id="conference-title" style={{ fontSize: 24, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}><Mic size={20} /> {t('Modo conferencia')}</h3>
          <p style={{ fontSize: 15, color: '#c7c2b0', marginTop: 4, maxWidth: 520 }}>{t('Escucha lo que se dice en español y lo traduce a maya en voz alta, frase por frase. Útil para seguir una charla en vivo con audífonos.')}</p>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
            <span style={{
              width: 10, height: 10, borderRadius: 10,
              background: avisoInactividad !== null && !hablando ? '#fb923c' : hablando ? '#60a5fa' : estadoMic === 'detectando' ? '#4ade80' : estadoMic === 'escuchando' ? '#c9a227' : '#6b7a6e',
              animation: estadoMic !== 'apagado' ? 'pulso-mic 1.1s ease-in-out infinite' : 'none',
            }} />
            <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: 0.5, color: avisoInactividad !== null && !hablando ? '#fb923c' : hablando ? '#60a5fa' : estadoMic === 'detectando' ? '#4ade80' : estadoMic === 'escuchando' ? '#c9a227' : '#8a9488' }}>
              {avisoInactividad !== null && !hablando ? `${t('SIN VOZ · se apagará en')} ${avisoInactividad} s` : hablando ? t('LEYENDO TRADUCCIÓN · micrófono en pausa') : estadoMic === 'detectando' ? t('¡DETECTANDO TU VOZ!') : estadoMic === 'escuchando' ? t('ESCUCHANDO · esperando que hables') : t('MICRÓFONO APAGADO')}
            </span>
          </div>
          <style>{`@keyframes pulso-mic { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.4); } }`}</style>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 20 }}>
            <Button onClick={escuchando ? detenerModoConferencia : iniciarModoConferencia} className="gap-2" variant={escuchando ? 'destructive' : 'default'}>
              {escuchando ? <><MicOff size={16} /> {t('Detener')}</> : <><Mic size={16} /> {t('Empezar a escuchar')}</>}
            </Button>
            <Button onClick={cambiarLecturaEnVoz} className="gap-2" variant="outline" aria-pressed={leerEnVoz}
              title={leerEnVoz ? t('Las traducciones se leen en voz alta') : t('Las traducciones solo se muestran en pantalla')}
              style={{ background: 'transparent', color: '#f5f2ec', borderColor: 'rgba(245,242,236,0.3)' }}>
              {leerEnVoz ? <><Volume2 size={16} /> {t('Voz activada')}</> : <><VolumeX size={16} /> {t('Voz apagada')}</>}
            </Button>
          </div>
          {avisoInactividad !== null && !hablando && (
            <Button onClick={seguirEscuchando} variant="outline" className="gap-2"
              style={{ marginTop: 12, background: 'transparent', color: '#fb923c', borderColor: '#fb923c' }}>
              <Mic size={16} /> {t('Sigo aquí, seguir escuchando')}
            </Button>
          )}
          {escuchando && (
            <p style={{ fontSize: 12, color: '#9aa89c', marginTop: 12 }}>
              {t('Tiempo de sesión')}: {minutos(segundosSesion)} / {minutos(DURACION_MAXIMA_S)}
            </p>
          )}
          <p style={{ fontSize: 12, color: '#9aa89c', marginTop: 10, maxWidth: 420 }}>
          </p>
        </div>

        <div aria-live="polite" style={{ flex: '1 1 320px', minWidth: 0, background: 'rgba(245,242,236,0.07)', border: '1px solid rgba(245,242,236,0.14)', borderRadius: 16, padding: 20, display: 'flex', flexDirection: 'column', gap: 14, minHeight: 200 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: '#9aa89c' }}>{t('Lo que estoy escuchando')}</span>
              <div title={t('Volumen del micrófono')} style={{ width: 90, height: 6, borderRadius: 6, background: 'rgba(245,242,236,0.12)', overflow: 'hidden' }}>
                <div ref={barraNivelRef} style={{ width: '0%', height: '100%', background: '#4ade80', transition: 'width 80ms linear' }} />
              </div>
            </div>
            <p style={{ marginTop: 8, fontSize: 18, minHeight: 27, color: textoEnVivo ? '#f5f2ec' : '#d8d2c2', fontStyle: textoEnVivo ? 'italic' : 'normal', opacity: textoEnVivo || ultimaFrase ? 1 : 0.6 }}>
              {textoEnVivo || ultimaFrase?.original || (escuchando ? t('Habla y aquí aparecerá el texto…') : t('Enciende el micrófono para empezar.'))}
            </p>
          </div>
          <div style={{ height: 1, background: 'rgba(245,242,236,0.14)' }} />
          <div>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#c9a227' }}>{t('Traducción al maya')}</span>
            <p style={{ marginTop: 8, fontSize: 20, fontWeight: 600, minHeight: 30, opacity: ultimaFrase?.traducido ? 1 : 0.6 }}>
              {ultimaFrase ? (ultimaFrase.traducido ?? t('Traduciendo…')) : t('La traducción de cada frase aparecerá aquí.')}
            </p>
          </div>
          {escuchando && (
            <div style={{ marginTop: 'auto', paddingTop: 10, borderTop: '1px dashed rgba(245,242,236,0.14)', fontSize: 12, color: '#9aa89c', display: 'flex', flexWrap: 'wrap', gap: '4px 12px' }}>
              <span>{t('Diagnóstico')}{motorVoz ? ` (${motorVoz === 'azure' ? 'Azure Speech' : t('navegador')})` : ` (${t('conectando…')})`}:</span>
              {([['inicio', tx('Inició')], ['audio', tx('Recibe audio')], ['sonido', tx('Oye sonido')], ['voz', tx('Reconoce voz')], ['resultado', tx('Da texto')]] as const).map(([clave, etiqueta]) => (
                <span key={clave} style={{ color: diagnostico[clave] ? '#4ade80' : '#8a9488' }}>{diagnostico[clave] ? '✓' : '○'} {t(etiqueta)}</span>
              ))}
              {diagnostico.reinicios > 0 && <span>Reinicios: {diagnostico.reinicios}</span>}
              {diagnostico.error && diagnostico.error !== 'no-speech' && <span style={{ color: '#f87171' }}>Error: {diagnostico.error}</span>}
            </div>
          )}
        </div>
      </div>
      {transcripcion.length > 0 && (
        <div style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 320, overflowY: 'auto' }}>
          <div style={{ display: 'flex', gap: 16, padding: '0 16px' }}>
            <span style={{ flex: 1, fontSize: 12, letterSpacing: 1, color: '#9aa89c', fontWeight: 700 }}>{t('ESPAÑOL (lo que dices)')}</span>
            <span style={{ flex: 1, fontSize: 12, letterSpacing: 1, color: '#c9a227', fontWeight: 700 }}>{t('MAYA YUCATECO (traducción)')}</span>
          </div>
          {transcripcion.map((linea, i) => (
            <div key={i} style={{ background: 'rgba(245,242,236,0.06)', borderRadius: 12, padding: '14px 16px', display: 'flex', gap: 16 }}>
              <p style={{ flex: 1, fontSize: 17, color: '#d8d2c2' }}>{linea.original}</p>
              <p style={{ flex: 1, fontSize: 17, fontWeight: 600 }}>{linea.traducido}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
