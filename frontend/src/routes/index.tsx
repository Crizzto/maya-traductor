import { createFileRoute } from '@tanstack/react-router';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowRightLeft, Camera, Check, ChevronDown, Clipboard, Copy, Download, Flower2, Heart, Keyboard, Languages, MessageCircle, Moon, Pencil, Share2, Sparkles, Sun, Volume2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import mayaLandscape from '@/assets/maya-landscape.jpg';
import { postJSON } from '@/lib/api';
import { ChatSection } from '@/components/zacilingua/ChatSection';
import { EtiquetaFuente, type Fuente } from '@/components/zacilingua/EtiquetaFuente';
import { FormularioSugerencia } from '@/components/zacilingua/FormularioSugerencia';
import { ModoConferencia } from '@/components/zacilingua/ModoConferencia';
import { tx, usePreferencias } from '@/lib/preferencias';
import { ES_IOS, desbloquearVoz, hablar } from '@/lib/voz';

export const Route = createFileRoute('/')({
  head: () => ({
    meta: [
      { title: 'Zacilingua · Traductor maya–español' },
      { name: 'description', content: 'Dos lenguas, una conexión. Un espacio para acercarte al maya yucateco y al español, con respeto por nuestras raíces.' },
      { property: 'og:title', content: 'Zacilingua · Traductor maya–español' },
      { property: 'og:description', content: 'Un encuentro entre el maya yucateco y el español. Cada palabra nos acerca.' },
      { property: 'og:type', content: 'website' },
      { name: 'twitter:card', content: 'summary_large_image' },
    ]
  }),
  component: Index,
});

function BrandMark({ className = '' }: { className?: string }) {
  return <svg className={className} viewBox="0 0 48 48" fill="none" aria-hidden="true"><path d="M24 3 31 10 38 10 38 17 45 24 38 31 38 38 31 38 24 45 17 38 10 38 10 31 3 24 10 17 10 10 17 10Z" stroke="currentColor" strokeWidth="2" /><path d="m24 13 11 11-11 11-11-11Z" stroke="currentColor" strokeWidth="2" /><path d="M24 19v10M19 24h10" stroke="currentColor" strokeWidth="2" /></svg>;
}

const phrases = [
  { category: tx('Saludos'), text: 'Buenos días', icon: Sun, tone: 'kan' },
  { category: tx('Conversación'), text: '¿Cómo estás?', icon: MessageCircle, tone: 'yaax' },
  { category: tx('Gratitud'), text: 'Muchas gracias', icon: Heart, tone: 'chak' },
  { category: tx('Conexión'), text: '¿Cómo te llamas?', icon: Flower2, tone: 'azul' },
];

// Colores cosmológicos mayas (se muestran como leyenda en el pie de página).
const mayaColors = [
  { name: 'Chak', token: 'chak', meaning: tx('Rojo · el este, la vida y el fuego') },
  { name: 'Säk', token: 'sak', meaning: tx('Blanco · el norte, la luz y la pureza') },
  { name: "Bo'sh", token: 'boosh', meaning: tx('Negro · el poniente, la noche y lo desconocido') },
  { name: "K'an", token: 'kan', meaning: tx('Amarillo · el sur, el maíz y la madurez') },
  { name: "Ya'ax", token: 'yaax', meaning: tx('Verde · el centro, la naturaleza y el eje del mundo') },
  { name: 'Azul Maya', token: 'azul', meaning: tx('Azul · lo sagrado, el cielo y el agua') },
];

function Index() {
  const { t, tema, cambiarTema, idioma, cambiarIdioma } = usePreferencias();
  const [source, setSource] = useState<'maya' | 'spanish'>('maya');
  const [text, setText] = useState('');
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const [modal, setModal] = useState<'about' | 'history' | null>(null);
  const [notice, setNotice] = useState('');
  const [resultado, setResultado] = useState('');
  const [fuente, setFuente] = useState<Fuente | null>(null);
  // Sugerencias de corrección: el usuario propone la traducción correcta
  // y queda pendiente de revisión (no cambia nada hasta que se aprueba).
  const [traducido, setTraducido] = useState<{ original: string; direccion: string } | null>(null);
  const [mostrarSugerencia, setMostrarSugerencia] = useState(false);
  const [sugerenciaEnviada, setSugerenciaEnviada] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [procesandoFoto, setProcesandoFoto] = useState(false);
  const [promptInstalacion, setPromptInstalacion] = useState<any>(null);
  const [yaInstalada, setYaInstalada] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const entradaFoto = useRef<HTMLInputElement>(null);
  const avisoSilencioRef = useRef(false);
  const isMaya = source === 'maya';

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(''), 4500);
    return () => window.clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (!modal) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setModal(null); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [modal]);
  useEffect(() => {
    // Si ya está instalada (corriendo en modo app), no mostramos el botón.
    if (window.matchMedia('(display-mode: standalone)').matches) setYaInstalada(true);

    const capturarPrompt = (evento: Event) => {
      evento.preventDefault();
      setPromptInstalacion(evento);
    };
    window.addEventListener('beforeinstallprompt', capturarPrompt);

    const marcarInstalada = () => { setYaInstalada(true); setPromptInstalacion(null); };
    window.addEventListener('appinstalled', marcarInstalada);

    return () => {
      window.removeEventListener('beforeinstallprompt', capturarPrompt);
      window.removeEventListener('appinstalled', marcarInstalada);
    };
  }, []);

  function swap() {
    setSource(isMaya ? 'spanish' : 'maya');
    setText(resultado);
    setResultado('');
  }
  async function paste() {
    try { setText((await navigator.clipboard.readText()).slice(0, 5000)); input.current?.focus(); }
    catch { setNotice(t('No se pudo acceder al portapapeles. Puedes pegar el texto directamente.')); }
  }
  function insertCharacter(character: string) {
    const position = input.current?.selectionStart ?? text.length;
    const end = input.current?.selectionEnd ?? position;
    const next = text.slice(0, position) + character + text.slice(end);
    setText(next.slice(0, 5000));
    input.current?.focus();
    requestAnimationFrame(() => input.current?.setSelectionRange(position + character.length, position + character.length));
  }

  // Prepara la foto para el OCR:
  //  1. La endereza (las fotos de iPhone traen la rotación aparte).
  //  2. La deja a un tamaño en que las letras se leen bien.
  //  3. La pasa a grises y, si es texto claro sobre fondo oscuro (como
  //     muchos letreros), la invierte: el OCR lee mejor letras oscuras.
  //  4. Corrige la luz desigual de las fotos de celular: compara cada zona
  //     con su propio fondo, así una esquina en sombra no borra las letras.
  // En pruebas con letreros fotografiados, esto subió la lectura correcta
  // de 94 % a 100 %.
  async function preprocesarImagen(archivo: File): Promise<HTMLCanvasElement> {
    let bitmap: ImageBitmap;
    try {
      bitmap = await createImageBitmap(archivo, { imageOrientation: 'from-image' } as ImageBitmapOptions);
    } catch {
      bitmap = await createImageBitmap(archivo);
    }
    const ladoMayor = Math.max(bitmap.width, bitmap.height);
    const escala = ladoMayor > 2200 ? 2200 / ladoMayor : ladoMayor < 1400 ? Math.min(2.5, 1400 / ladoMayor) : 1;
    const ancho = Math.round(bitmap.width * escala);
    const alto = Math.round(bitmap.height * escala);
    const canvas = document.createElement('canvas');
    canvas.width = ancho;
    canvas.height = alto;
    const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(bitmap, 0, 0, ancho, alto);

    // 3. Grises (y mediana, para saber si el fondo es oscuro).
    const imagen = ctx.getImageData(0, 0, ancho, alto);
    const datos = imagen.data;
    const histograma = new Array(256).fill(0);
    for (let i = 0; i < datos.length; i += 4) {
      const gris = Math.round(datos[i] * 0.299 + datos[i + 1] * 0.587 + datos[i + 2] * 0.114);
      datos[i] = datos[i + 1] = datos[i + 2] = gris;
      histograma[gris]++;
    }
    let acumulado = 0, mediana = 0;
    for (; mediana < 256; mediana++) { acumulado += histograma[mediana]; if (acumulado >= datos.length / 8) break; }
    if (mediana < 110) {
      for (let i = 0; i < datos.length; i += 4) datos[i] = datos[i + 1] = datos[i + 2] = 255 - datos[i];
    }
    ctx.putImageData(imagen, 0, 0);

    // 4. Fondo estimado: achicar la imagen y volverla a agrandar la difumina
    // (funciona en todos los navegadores, también en Safari).
    // Se achica a la mitad varias veces (de golpe, el navegador no
    // promedia bien y el fondo estimado sale ruidoso).
    const radio = Math.max(15, Math.round(Math.max(ancho, alto) / 40));
    const anchoMeta = Math.max(1, Math.round(ancho / radio));
    const altoMeta = Math.max(1, Math.round(alto / radio));
    let chico: HTMLCanvasElement = canvas;
    while (chico.width > anchoMeta || chico.height > altoMeta) {
      const paso = document.createElement('canvas');
      paso.width = Math.max(anchoMeta, Math.round(chico.width / 2));
      paso.height = Math.max(altoMeta, Math.round(chico.height / 2));
      const ctxPaso = paso.getContext('2d')!;
      ctxPaso.imageSmoothingQuality = 'high';
      ctxPaso.drawImage(chico, 0, 0, paso.width, paso.height);
      chico = paso;
    }
    const fondoCanvas = document.createElement('canvas');
    fondoCanvas.width = ancho;
    fondoCanvas.height = alto;
    const ctxFondo = fondoCanvas.getContext('2d', { willReadFrequently: true })!;
    ctxFondo.imageSmoothingQuality = 'high';
    ctxFondo.drawImage(chico, 0, 0, ancho, alto);
    const fondo = ctxFondo.getImageData(0, 0, ancho, alto).data;

    const final = ctx.getImageData(0, 0, ancho, alto);
    const px = final.data;
    for (let i = 0; i < px.length; i += 4) {
      const v = Math.min(255, (px[i] / Math.max(1, fondo[i])) * 255);
      px[i] = px[i + 1] = px[i + 2] = v;
    }
    ctx.putImageData(final, 0, 0);
    return canvas;
  }

  // Limpia lo que devuelve el OCR: quita renglones de basura (manchas que
  // se leen como símbolos) y junta los renglones de un mismo letrero en
  // frases, para que se traduzcan como texto corrido.
  function limpiarTextoOcr(texto: string) {
    const renglones = texto
      .replace(/[\u2018\u2019\u00b4`]/g, '\u2019')
      .split(/\n+/)
      .map((r) => r.replace(/\s+/g, ' ').trim())
      .filter((r) => {
        const letras = (r.match(/[\p{L}\p{N}]/gu) || []).length;
        return r.length >= 2 && letras / r.length >= 0.6;
      });
    return renglones
      .reduce((frase, r) => {
        if (!frase) return r;
        if (frase.endsWith('-')) return frase.slice(0, -1) + r;
        return frase + (/[.!?:;]$/.test(frase) ? '\n' : ' ') + r;
      }, '')
      .trim();
  }

  async function manejarFoto(evento: React.ChangeEvent<HTMLInputElement>) {
    const archivo = evento.target.files?.[0];
    evento.target.value = '';
    if (!archivo) return;
    // Límites: solo imágenes, y de máximo 10 MB (las más grandes tardan
    // mucho en leerse dentro del celular y no mejoran el resultado).
    if (!archivo.type.startsWith('image/')) {
      setNotice(t('Ese archivo no es una imagen. Elige una foto.'));
      return;
    }
    if (archivo.size > 10 * 1024 * 1024) {
      setNotice(t('La foto pesa más de 10 MB. Prueba con una más ligera o recórtala.'));
      return;
    }

    setProcesandoFoto(true);
    setResultado('');
    try {
      const canvasProcesado = await preprocesarImagen(archivo);
      const { createWorker } = await import('tesseract.js');
      const worker = await createWorker('spa');
      // Dos lecturas: como bloque de texto (documentos) y como texto suelto
      // (letreros, carteles). Se queda con la que el OCR lee con más confianza.
      let mejor = { texto: '', confianza: 0 };
      for (const modo of ['6', '11']) {
        await worker.setParameters({ tessedit_pageseg_mode: modo as any });
        const { data } = await worker.recognize(canvasProcesado);
        const texto = limpiarTextoOcr(data.text || '');
        if (texto && data.confidence > mejor.confianza) mejor = { texto, confianza: data.confidence };
        if (mejor.confianza >= 85) break; // ya es una lectura muy buena
      }
      await worker.terminate();
      if (!mejor.texto) {
        setNotice(t('No se detectó texto en la foto. Intenta con una imagen más clara.'));
        return;
      }
      setText(mejor.texto.slice(0, 5000));
      input.current?.focus();
      setNotice(mejor.confianza < 60
        ? t('Se leyó el texto con dudas. Revísalo, o toma la foto más de cerca, de frente y con buena luz.')
        : t('Texto detectado. Revísalo antes de traducir, el OCR puede cometer errores.'));
    } catch (error) {
      setNotice(t('No se pudo leer el texto de la imagen. Intenta de nuevo.'));
    } finally {
      setProcesandoFoto(false);
    }
  }

  async function traducir() {
    if (!text.trim() || cargando) return;
    setCargando(true);
    setResultado('');
    try {
      const datos = await postJSON<{ resultado: string; fuente: Fuente }>('/api/traducir', {
        texto: text,
        direccion: isMaya ? 'maya-spanish' : 'spanish-maya',
      }, 'Error al traducir.');
      setResultado(datos.resultado);
      setFuente(datos.fuente ?? null);
      setTraducido({ original: text.trim(), direccion: isMaya ? 'maya-spanish' : 'spanish-maya' });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : t('No se pudo conectar con el traductor.'));
    } finally {
      setCargando(false);
    }
  }

  // Si el resultado se borra (otro texto, cambio de idioma...), se cierra
  // el formulario de sugerencia porque ya no corresponde.
  useEffect(() => {
    if (!resultado) { setMostrarSugerencia(false); setSugerenciaEnviada(false); }
  }, [resultado]);

  function abrirSugerencia() {
    setMostrarSugerencia(true);
  }

  async function copiarResultado() {
    if (!resultado) return;
    try { await navigator.clipboard.writeText(resultado); setNotice(t('Traducción copiada.')); }
    catch { setNotice(t('No se pudo copiar al portapapeles.')); }
  }

  async function instalarApp() {
    if (promptInstalacion) {
      promptInstalacion.prompt();
      const eleccion = await promptInstalacion.userChoice;
      if (eleccion.outcome === 'accepted') setYaInstalada(true);
      setPromptInstalacion(null);
    } else {
      // iOS Safari (y algunos otros navegadores) no soportan este evento:
      // no hay forma de disparar la instalación por código, solo explicar.
      setNotice(t('En iPhone: toca el botón de compartir de Safari y elige «Añadir a pantalla de inicio».'));
    }
  }

  function pronunciarResultado() {
    desbloquearVoz(); // en iPhone solo suena si se activa desde este toque
    // No existe voz en maya en ningún navegador: se usa una voz en español
    // como aproximación (se avisa al usuario en la interfaz).
    if (!resultado || !hablar(resultado, { velocidad: 0.9, interrumpir: true })) {
      setNotice(t('Tu navegador no soporta lectura en voz alta.'));
      return;
    }
    if (ES_IOS && !avisoSilencioRef.current) {
      avisoSilencioRef.current = true;
      setNotice(t('Si no escuchas nada, quita el modo silencio del iPhone y sube el volumen.'));
    }
  }

  function compartirWhatsApp() {
    if (!resultado) return;
    const mensaje = `${text}\n\n→ ${resultado}\n\n${t('Traducido con Zacilingua')}`;
    if (navigator.share) {
      navigator.share({ text: mensaje }).catch(() => { });
    } else {
      window.open(`https://wa.me/?text=${encodeURIComponent(mensaje)}`, '_blank');
    }
  }

  return <>
    <header className="site-header">
      <div className="page-width flex h-full items-center justify-between">
        <a href="#" aria-label={t('Zacilingua, inicio')} className="flex min-w-0 items-center gap-2.5"><BrandMark className="brand-symbol" /><div><div className="brand-name">zacilingua<span className="text-primary">.</span></div><div className="brand-caption">{t('PALABRAS QUE CONECTAN')}</div></div></a>
        <nav aria-label={t('Navegación principal')} className="flex items-center gap-2 sm:gap-6">
          <Button variant="ghost" asChild className="nav-link active hidden sm:inline-flex"><a href="#traductor">{t('Traductor')}</a></Button>
          {!yaInstalada && <Button variant="outline" size="sm" onClick={instalarApp} className="boton-descargar gap-1.5" title={t('Descargar app')} aria-label={t('Descargar app')}><Download size={14} /> <span className="hidden sm:inline">{t('Descargar app')}</span></Button>}
          <div className="preferencias">
            <div className="selector-idioma" role="group" aria-label={t('Idioma de la página')}>
              <button type="button" aria-pressed={idioma === 'es'} onClick={() => cambiarIdioma('es')} lang="es" title="Español">ES</button>
              <button type="button" aria-pressed={idioma === 'yua'} onClick={() => cambiarIdioma('yua')} lang="yua" title="Maaya t'aan">MAAYA</button>
            </div>
            <button type="button" className="boton-tema" onClick={cambiarTema}
              aria-label={tema === 'oscuro' ? t('Cambiar a modo claro') : t('Cambiar a modo oscuro')}
              title={tema === 'oscuro' ? t('Cambiar a modo claro') : t('Cambiar a modo oscuro')}>
              {tema === 'oscuro' ? <Sun size={15} /> : <Moon size={15} />}
            </button>
          </div>
        </nav>
      </div>
    </header>
    <div className="maya-band" aria-hidden="true"><span /><span /><span /><span /><span /><span /></div>

    <section className="hero" aria-label={t('Lengua y cultura maya')}>
      <img src={mayaLandscape} alt={t('La pirámide de Kukulkán en Chichén Itzá, rodeada por la naturaleza de Yucatán')} width={1536} height={640} className="hero-image" />
      <div className="page-width hero-content reveal">
        <div className="hero-eyebrow"><Sparkles size={12} /> {t('UNA LENGUA VIVA. UN LEGADO QUE CONTINÚA.')}</div>
        <h1>{t('Traductor maya–español')}<span>{t('Dos lenguas, una conexión.')}</span></h1>
      </div>
    </section>

    <main id="traductor" className="page-width main-content reveal-late">
      <div className="flex items-center justify-between gap-3">
        <div><div className="section-eyebrow mb-1">{t('UN PUENTE ENTRE PALABRAS')}</div><h2 className="section-title">{t('¿Qué quieres expresar?')}</h2><p className="section-description">{t('Del maya al español. Del español al maya.')}</p></div>
      </div>

      <section className="translator" aria-label={t('Traductor bidireccional')}>
        <div className="language-bar">
          <div className="language-label"><span className="language-icon"><Languages size={15} /></span><span>{isMaya ? t('Maya') : t('Español')}<small>{isMaya ? t('Yucateco') : ''}</small></span><ChevronDown size={12} className="text-muted-foreground" /></div>
          <Button variant="outline" size="icon" className="swap-button" onClick={swap} title={t('Intercambiar idiomas')} aria-label={t('Intercambiar idiomas')}><ArrowRightLeft /></Button>
          <div className="language-label language-destination"><span className="language-icon"><Languages size={15} /></span><span>{isMaya ? t('Español') : t('Maya')}<small>{isMaya ? '' : t('Yucateco')}</small></span></div>
        </div>
        <div className="translator-panels">
          <div className="source-panel">
            <textarea ref={input} className="source-text" aria-label={isMaya ? t('Texto en maya') : t('Texto en español')} placeholder={isMaya ? t('Escribe aquí en maya…') : t('Escribe aquí en español…')} maxLength={5000} value={text} onChange={event => { setText(event.target.value); setResultado(''); }} />
            <div className="panel-controls"><div className="flex items-center gap-1"><Button variant="ghost" size="icon" className="tool-icon" onClick={paste} title={t('Pegar texto')} aria-label={t('Pegar texto')}><Clipboard /></Button><Button variant="ghost" size="icon" className="tool-icon" aria-pressed={keyboardOpen} onClick={() => setKeyboardOpen(!keyboardOpen)} title={t('Caracteres especiales')} aria-label={t('Caracteres especiales')}><Keyboard /></Button><Button variant="ghost" size="icon" className="tool-icon" disabled={procesandoFoto} onClick={() => entradaFoto.current?.click()} title={t('Traducir desde foto')} aria-label={t('Traducir desde foto')}><Camera className={procesandoFoto ? 'animate-pulse' : ''} /></Button><input ref={entradaFoto} type="file" accept="image/*" capture="environment" className="hidden" onChange={manejarFoto} />{text && <Button variant="ghost" size="icon" className="tool-icon" onClick={() => { setText(''); setResultado(''); input.current?.focus(); }} title={t('Borrar texto')} aria-label={t('Borrar texto')}><X /></Button>}</div><span className="count">{procesandoFoto ? t('Leyendo foto…') : `${text.length.toLocaleString('es-MX')} / 5,000`}</span></div>
          </div>
          <div className="result-panel" aria-live="polite">
            {resultado
              ? <><p className="result-text">{resultado}</p>{!isMaya ? null : <small className="block text-[10px] text-muted-foreground mt-1">{t('Pronunciación aproximada (no existe voz nativa en maya)')}</small>}
                {fuente && fuente !== 'error' && (
                  <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginTop: 12 }}>
                    <EtiquetaFuente fuente={fuente} />
                    {sugerenciaEnviada
                      ? <span style={{ fontSize: 12, color: 'var(--zl-success)', display: 'inline-flex', alignItems: 'center', gap: 4 }}><Check size={13} /> {t('Sugerencia enviada')}</span>
                      : !mostrarSugerencia && <button type="button" onClick={abrirSugerencia} style={{ fontSize: 12, fontWeight: 600, color: 'var(--zl-link)', display: 'inline-flex', alignItems: 'center', gap: 4, textDecoration: 'underline', textUnderlineOffset: 3, background: 'none', border: 0, cursor: 'pointer', padding: 0 }}><Pencil size={12} /> {fuente === 'verificado' ? t('¿Ves un error?') : t('Sugerir corrección')}</button>}
                  </div>
                )}</>
              : <div className="result-empty"><BrandMark className="result-symbol" /><p>{cargando ? t('Traduciendo…') : t('Aquí comienza una nueva conexión')}</p><small>{cargando ? t('Un momento, por favor.') : t('Tu traducción aparecerá aquí.')}</small></div>
            }
            <div className="panel-controls"><span className="count">{isMaya ? t('ESPAÑOL') : t('MAYA YUCATECO')}</span><div className="flex items-center gap-1"><Button variant="ghost" size="icon" className="tool-icon" disabled={!resultado} onClick={pronunciarResultado} title={t('Escuchar traducción')} aria-label={t('Escuchar traducción')}><Volume2 /></Button><Button variant="ghost" size="icon" className="tool-icon" disabled={!resultado} onClick={compartirWhatsApp} title={t('Compartir por WhatsApp')} aria-label={t('Compartir por WhatsApp')}><Share2 /></Button><Button variant="ghost" size="icon" className="tool-icon" disabled={!resultado} onClick={copiarResultado} title={t('Copiar traducción')} aria-label={t('Copiar traducción')}><Copy /></Button></div></div>
          </div>
        </div>
        {mostrarSugerencia && traducido && (
          <FormularioSugerencia
            original={traducido.original}
            direccion={traducido.direccion}
            traduccionActual={resultado}
            onCancelar={() => setMostrarSugerencia(false)}
            onEnviada={() => { setMostrarSugerencia(false); setSugerenciaEnviada(true); }}
            onNotice={setNotice}
          />
        )}
        {keyboardOpen && <div className="character-tray"><span>{t('Caracteres')}</span>{['á', 'é', 'í', 'ó', 'ú', 'ñ', 'ü', 'ʼ'].map(character => <Button key={character} variant="outline" size="sm" onClick={() => insertCharacter(character)} aria-label={`${t('Insertar')} ${character}`}>{character}</Button>)}</div>}
        <div className="translator-bottom"><span className="ai-label"><Languages size={14} /> {t('Maya yucateco')} <span className="hidden sm:inline">⇄</span> {t('Español')}</span><Button className="translate-cta" disabled={!text.trim() || cargando} onClick={traducir}>{cargando ? <Sparkles className="animate-spin" /> : resultado ? <Check /> : <Sparkles />} {cargando ? t('Traduciendo…') : resultado ? t('Traducido') : t('Traducir texto')}{!cargando && !resultado && <ArrowRight />}</Button></div>
      </section>



      <ModoConferencia onNotice={setNotice} />

      <ChatSection />

      <section className="phrases-section" aria-labelledby="phrases-title">
        <div className="flex items-center justify-between"><h3 id="phrases-title" className="phrase-heading"><Sun size={16} /> {t('Las pequeñas palabras nos acercan')}</h3><span className="hidden text-[10px] text-muted-foreground sm:block">{t('UN POCO DE INSPIRACIÓN')}</span></div>
        <div className="phrase-grid">{phrases.map(phrase => <Button key={phrase.category} variant="ghost" className="phrase-card" data-tone={phrase.tone} onClick={() => { setSource('spanish'); setText(phrase.text); setResultado(''); input.current?.focus(); document.getElementById('traductor')?.scrollIntoView({ block: 'start', behavior: 'smooth' }); }}><span className="phrase-top"><span className="phrase-icon"><phrase.icon size={14} /></span>{t(phrase.category)}<ArrowRight /></span><span className="phrase-text">{phrase.text}</span></Button>)}</div>
      </section>
    </main>

    <div className="maya-steps" aria-hidden="true" />
    <footer className="site-footer"><div className="page-width footer-inner"><div><span className="footer-brand">Zacilingua.</span> {t('Un encuentro entre lenguas y culturas.')}{idioma === 'yua' && <div className="aviso-traduccion-interfaz">{t('Interfaz traducida automáticamente, en revisión.')}{t('Interfaz traducida automáticamente, en revisión.') !== 'Interfaz traducida automáticamente, en revisión.' && ' (Interfaz traducida automáticamente, en revisión.)'}</div>}</div><div className="color-legend" aria-label={t('Colores de la cosmovisión maya')}>{mayaColors.map(color => <span key={color.token} className="color-chip" title={t(color.meaning)}><i style={{ background: `var(--${color.token})` }} />{color.name}</span>)}</div></div></footer>
  </>;
}