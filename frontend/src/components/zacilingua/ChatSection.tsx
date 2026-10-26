// Chat: modo simple (detecta el idioma y traduce cada mensaje) o modo
// agente (conversa con Gemini, que usa el traductor y los diccionarios
// como herramientas).
import { useEffect, useRef, useState } from 'react';
import { MessageSquare, Send, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { postJSON } from '@/lib/api';
import { EtiquetaFuente, type Fuente } from './EtiquetaFuente';
import { TextoMarkdown } from './TextoMarkdown';
import { useT } from '@/lib/preferencias';

export function ChatSection() {
  const t = useT();
  const [mensajesChat, setMensajesChat] = useState<{ texto: string; idioma?: 'es' | 'yua'; fuente?: Fuente; esUsuario: boolean }[]>([]);
  const [textoChat, setTextoChat] = useState('');
  const [enviandoChat, setEnviandoChat] = useState(false);
  const [modoAgente, setModoAgente] = useState(false);
  const historialAgenteRef = useRef<any[]>([]); // historial en formato Gemini, no se muestra directo en pantalla
  const finChat = useRef<HTMLDivElement>(null);

  useEffect(() => {
    finChat.current?.scrollIntoView({ behavior: 'smooth' });
  }, [mensajesChat]);

  async function enviarMensajeChat() {
    const texto = textoChat.trim();
    if (!texto || enviandoChat) return;
    setTextoChat('');
    setEnviandoChat(true);
    setMensajesChat((previos) => [...previos, { texto, esUsuario: true }]);

    if (modoAgente) {
      try {
        const datos = await postJSON<{ respuesta: string }>('/api/agente', { mensaje: texto, historial: historialAgenteRef.current }, 'El agente no respondió.');
        // Guardamos el turno en el historial (formato que espera Gemini)
        // para que la siguiente pregunta tenga contexto de esta conversación.
        historialAgenteRef.current = [
          ...historialAgenteRef.current,
          { role: 'user', parts: [{ text: texto }] },
          { role: 'model', parts: [{ text: datos.respuesta }] },
        ];
        setMensajesChat((previos) => [...previos, { texto: datos.respuesta, esUsuario: false }]);
      } catch (error) {
        setMensajesChat((previos) => [...previos, { texto: error instanceof Error ? `⚠ ${error.message}` : `⚠ ${t('El agente no pudo responder.')}`, esUsuario: false }]);
      } finally {
        setEnviandoChat(false);
      }
      return;
    }

    try {
      const datos = await postJSON<{ resultado: string; idioma_detectado: string; fuente: Fuente }>('/api/chat', { texto }, 'No se pudo traducir ese mensaje.');
      setMensajesChat((previos) => [...previos, { texto: datos.resultado, idioma: datos.idioma_detectado === 'es' ? 'yua' : 'es', fuente: datos.fuente, esUsuario: false }]);
    } catch (error) {
      setMensajesChat((previos) => [...previos, { texto: `⚠ ${error instanceof Error ? error.message : t('No se pudo traducir ese mensaje.')}`, esUsuario: false }]);
    } finally {
      setEnviandoChat(false);
    }
  }

  return (
      <section className="chat-section" aria-labelledby="chat-title" style={{ marginTop: 24, background: 'var(--zl-surface)', color: 'var(--zl-text)', border: '1px solid var(--zl-border-soft)', borderRadius: 24, padding: 32, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <h3 id="chat-title" style={{ fontSize: 22, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}><MessageSquare size={18} /> {t('Chat')}</h3>
            <p style={{ fontSize: 14, color: 'var(--zl-text-faint)', marginTop: 2 }}>{modoAgente ? t('Agente con Gemini: puede explicar, conversar y traducir cuando lo necesite.') : t('Escribe en español o en maya, sin elegir dirección — se detecta sola.')}</p>
          </div>
          <Button
            variant="outline" size="sm" className="gap-1.5"
            onClick={() => { setModoAgente(!modoAgente); setMensajesChat([]); historialAgenteRef.current = []; }}
          >
            <Sparkles size={14} /> {modoAgente ? t('Usar chat simple') : t('Usar agente (Gemini)')}
          </Button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 320, overflowY: 'auto', minHeight: mensajesChat.length ? undefined : 0 }}>
          {mensajesChat.map((m, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: m.esUsuario ? 'flex-end' : 'flex-start' }}>
              <div style={{
                maxWidth: '75%', padding: '10px 16px', borderRadius: 16,
                background: m.esUsuario ? 'var(--zl-bubble-user-bg)' : 'var(--zl-bubble-bot-bg)',
                color: m.esUsuario ? 'var(--zl-bubble-user-fg)' : 'var(--zl-bubble-bot-fg)',
                borderBottomRightRadius: m.esUsuario ? 4 : 16,
                borderBottomLeftRadius: m.esUsuario ? 16 : 4,
              }}>
                {!m.esUsuario && m.idioma && <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.5, color: 'var(--zl-accent-label)', display: 'block', marginBottom: 2 }}>{m.idioma === 'yua' ? t('MAYA YUCATECO') : t('ESPAÑOL')}{m.fuente && <span style={{ marginLeft: 6, verticalAlign: 'middle' }}><EtiquetaFuente fuente={m.fuente} compacta /></span>}</span>}
                {m.esUsuario || m.idioma
                  ? <span style={{ fontSize: 16 }}>{m.texto}</span>
                  : <div style={{ fontSize: 16 }}><TextoMarkdown texto={m.texto} /></div>}
              </div>
            </div>
          ))}
          {enviandoChat && <div style={{ fontSize: 13, color: 'var(--zl-text-faint)', fontStyle: 'italic' }}>{modoAgente ? t('Pensando…') : t('Traduciendo…')}</div>}
          <div ref={finChat} />
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            value={textoChat}
            onChange={(e) => setTextoChat(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') enviarMensajeChat(); }}
            placeholder={t('Escribe un mensaje…')}
            style={{ flex: 1, border: '1px solid var(--zl-border-soft)', borderRadius: 999, padding: '10px 18px', fontSize: 16, outline: 'none', background: 'var(--zl-input)', color: 'var(--zl-text)' }}
          />
          <Button size="icon" onClick={enviarMensajeChat} disabled={!textoChat.trim() || enviandoChat} className="rounded-full" aria-label={t('Enviar')}><Send size={16} /></Button>
        </div>
      </section>
  );
}
