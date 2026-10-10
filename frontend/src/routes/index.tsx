import { createFileRoute } from '@tanstack/react-router';
import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowRight, ArrowRightLeft, Check, ChevronDown, Clipboard, Copy, Flower2, Heart, History, Keyboard, Languages, Leaf, MapPin, MessageCircle, Sparkles, Sun, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import mayaLandscape from '@/assets/maya-landscape.jpg';

export const Route = createFileRoute('/')({
  head: () => ({ meta: [
    { title: 'Zacilingua · Traductor maya–español' },
    { name: 'description', content: 'Dos lenguas, una conexión. Un espacio para acercarte al maya yucateco y al español, con respeto por nuestras raíces.' },
    { property: 'og:title', content: 'Zacilingua · Traductor maya–español' },
    { property: 'og:description', content: 'Un encuentro entre el maya yucateco y el español. Cada palabra nos acerca.' },
    { property: 'og:type', content: 'website' },
    { name: 'twitter:card', content: 'summary_large_image' },
  ] }),
  component: Index,
});

function BrandMark({ className = '' }: { className?: string }) {
  return <svg className={className} viewBox="0 0 48 48" fill="none" aria-hidden="true"><path d="M24 3 31 10 38 10 38 17 45 24 38 31 38 38 31 38 24 45 17 38 10 38 10 31 3 24 10 17 10 10 17 10Z" stroke="currentColor" strokeWidth="2" /><path d="m24 13 11 11-11 11-11-11Z" stroke="currentColor" strokeWidth="2" /><path d="M24 19v10M19 24h10" stroke="currentColor" strokeWidth="2" /></svg>;
}

const phrases = [
  { category: 'Saludos', text: 'Buenos días', icon: Sun, tone: 'gold' },
  { category: 'Conversación', text: '¿Cómo estás?', icon: MessageCircle, tone: 'green' },
  { category: 'Gratitud', text: 'Muchas gracias', icon: Heart, tone: 'clay' },
  { category: 'Conexión', text: '¿Cómo te llamas?', icon: Flower2, tone: 'lavender' },
];

// En desarrollo, el backend Flask corre en 127.0.0.1:8001 (ver tranlate.py).
// Si lo despliegas, pon la URL real aquí o mejor como variable de entorno
// de Vite (import.meta.env.VITE_API_URL).
const API_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8001';

function Index() {
  const [source, setSource] = useState<'maya' | 'spanish'>('maya');
  const [text, setText] = useState('');
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const [modal, setModal] = useState<'about' | 'history' | null>(null);
  const [notice, setNotice] = useState('');
  const [resultado, setResultado] = useState('');
  const [cargando, setCargando] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
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

  function swap() {
    setSource(isMaya ? 'spanish' : 'maya');
    setText(resultado);
    setResultado('');
  }
  async function paste() {
    try { setText((await navigator.clipboard.readText()).slice(0, 5000)); input.current?.focus(); }
    catch { setNotice('No se pudo acceder al portapapeles. Puedes pegar el texto directamente.'); }
  }
  function insertCharacter(character: string) {
    const position = input.current?.selectionStart ?? text.length;
    const end = input.current?.selectionEnd ?? position;
    const next = text.slice(0, position) + character + text.slice(end);
    setText(next.slice(0, 5000));
    input.current?.focus();
    requestAnimationFrame(() => input.current?.setSelectionRange(position + character.length, position + character.length));
  }

  async function traducir() {
    if (!text.trim() || cargando) return;
    setCargando(true);
    setResultado('');
    try {
      const respuesta = await fetch(`${API_URL}/api/traducir`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          texto: text,
          direccion: isMaya ? 'maya-spanish' : 'spanish-maya',
        }),
      });
      const datos = await respuesta.json();
      if (!respuesta.ok) throw new Error(datos.error || 'Error al traducir.');
      setResultado(datos.resultado);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'No se pudo conectar con el traductor.');
    } finally {
      setCargando(false);
    }
  }

  async function copiarResultado() {
    if (!resultado) return;
    try { await navigator.clipboard.writeText(resultado); setNotice('Traducción copiada.'); }
    catch { setNotice('No se pudo copiar al portapapeles.'); }
  }

  return <>
    <header className="site-header">
      <div className="page-width flex h-full items-center justify-between">
        <a href="#" aria-label="Zacilingua, inicio" className="flex items-center gap-2.5"><BrandMark className="brand-symbol" /><div><div className="brand-name">zacilingua<span className="text-primary">.</span></div><div className="brand-caption">PALABRAS QUE CONECTAN</div></div></a>
        <nav aria-label="Navegación principal" className="flex items-center gap-6 sm:gap-9">
          <Button variant="ghost" asChild className="nav-link active"><a href="#traductor">Traductor</a></Button>
          <span className="hidden items-center gap-1.5 border-l border-border pl-5 text-xs text-muted-foreground sm:flex"><Languages size={14} /> ES</span>
        </nav>
      </div>
    </header>

    <section className="hero" aria-label="Lengua y cultura maya">
      <img src={mayaLandscape} alt="La pirámide de Kukulkán en Chichén Itzá, rodeada por la naturaleza de Yucatán" width={1536} height={640} className="hero-image" />
      <div className="page-width hero-content reveal">
        <div className="hero-eyebrow"><Sparkles size={12} /> UNA LENGUA VIVA. UN LEGADO QUE CONTINÚA.</div>
        <h1>Traductor maya–español<span>Dos lenguas, una conexión.</span></h1>
      </div>
    </section>

    <main id="traductor" className="page-width main-content reveal-late">
      <div className="flex items-center justify-between gap-3">
        <div><div className="section-eyebrow mb-1">UN PUENTE ENTRE PALABRAS</div><h2 className="section-title">¿Qué quieres expresar?</h2><p className="section-description">Del maya al español. Del español al maya.</p></div>
      </div>

      <section className="translator" aria-label="Traductor bidireccional">
        <div className="language-bar">
          <div className="language-label"><span className="language-icon"><Languages size={15} /></span><span>{isMaya ? 'Maya' : 'Español'}<small>{isMaya ? 'Yucateco' : ''}</small></span><ChevronDown size={12} className="text-muted-foreground" /></div>
          <Button variant="outline" size="icon" className="swap-button" onClick={swap} title="Intercambiar idiomas" aria-label="Intercambiar idiomas"><ArrowRightLeft /></Button>
          <div className="language-label language-destination"><span className="language-icon"><Languages size={15} /></span><span>{isMaya ? 'Español' : 'Maya'}<small>{isMaya ? '' : 'Yucateco'}</small></span></div>
        </div>
        <div className="translator-panels">
          <div className="source-panel">
            <textarea ref={input} className="source-text" aria-label={`Texto en ${isMaya ? 'maya' : 'español'}`} placeholder={`Escribe aquí en ${isMaya ? 'maya' : 'español'}…`} maxLength={5000} value={text} onChange={event => { setText(event.target.value); setResultado(''); }} />
            <div className="panel-controls"><div className="flex items-center gap-1"><Button variant="ghost" size="icon" className="tool-icon" onClick={paste} title="Pegar texto" aria-label="Pegar texto"><Clipboard /></Button><Button variant="ghost" size="icon" className="tool-icon" aria-pressed={keyboardOpen} onClick={() => setKeyboardOpen(!keyboardOpen)} title="Caracteres especiales" aria-label="Caracteres especiales"><Keyboard /></Button>{text && <Button variant="ghost" size="icon" className="tool-icon" onClick={() => { setText(''); setResultado(''); input.current?.focus(); }} title="Borrar texto" aria-label="Borrar texto"><X /></Button>}</div><span className="count">{text.length.toLocaleString('es-MX')} / 5,000</span></div>
          </div>
          <div className="result-panel" aria-live="polite">
            {resultado
              ? <p className="result-text">{resultado}</p>
              : <div className="result-empty"><BrandMark className="result-symbol" /><p>{cargando ? 'Traduciendo…' : 'Aquí comienza una nueva conexión'}</p><small>{cargando ? 'Un momento, por favor.' : 'Tu traducción aparecerá aquí.'}</small></div>
            }
            <div className="panel-controls"><span className="count">{isMaya ? 'ESPAÑOL' : 'MAYA YUCATECO'}</span><Button variant="ghost" size="icon" className="tool-icon" disabled={!resultado} onClick={copiarResultado} title="Copiar traducción" aria-label="Copiar traducción"><Copy /></Button></div>
          </div>
        </div>
        {keyboardOpen && <div className="character-tray"><span>Caracteres</span>{['á', 'é', 'í', 'ó', 'ú', 'ñ', 'ü', 'ʼ'].map(character => <Button key={character} variant="outline" size="sm" onClick={() => insertCharacter(character)} aria-label={`Insertar ${character}`}>{character}</Button>)}</div>}
        <div className="translator-bottom"><span className="ai-label"><Languages size={14} /> Maya yucateco <span className="hidden sm:inline">⇄</span> Español</span><Button className="translate-cta" disabled={!text.trim() || cargando} onClick={traducir}>{cargando ? <Sparkles className="animate-spin" /> : resultado ? <Check /> : <Sparkles />} {cargando ? 'Traduciendo…' : resultado ? 'Traducido' : 'Traducir texto'}{!cargando && !resultado && <ArrowRight />}</Button></div>
      </section>

      <section className="phrases-section" aria-labelledby="phrases-title">
        <div className="flex items-center justify-between"><h3 id="phrases-title" className="phrase-heading"><Sun size={16} /> Las pequeñas palabras nos acercan</h3><span className="hidden text-[10px] text-muted-foreground sm:block">UN POCO DE INSPIRACIÓN</span></div>
        <div className="phrase-grid">{phrases.map(phrase => <Button key={phrase.category} variant="ghost" className="phrase-card" data-tone={phrase.tone} onClick={() => { setSource('spanish'); setText(phrase.text); setResultado(''); input.current?.focus(); document.getElementById('traductor')?.scrollIntoView({ block: 'start', behavior: 'smooth' }); }}><span className="phrase-top"><span className="phrase-icon"><phrase.icon size={14} /></span>{phrase.category}<ArrowRight /></span><span className="phrase-text">{phrase.text}</span></Button>)}</div>
      </section>
    </main>

    <footer className="site-footer"><div className="page-width footer-inner"><div><span className="footer-brand">Zacilingua.</span> Un encuentro entre lenguas y culturas.</div></div></footer>

   
  </>;
}