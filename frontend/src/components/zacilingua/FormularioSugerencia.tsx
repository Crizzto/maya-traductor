// Formulario para proponer una traducción mejor. La sugerencia queda
// pendiente de revisión en el backend (no cambia nada hasta aprobarla
// con revisar_sugerencias.py).
import { useState } from 'react';
import { Send } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { postJSON } from '@/lib/api';
import { useT } from '@/lib/preferencias';

type Props = {
  original: string;
  direccion: string;
  traduccionActual: string;
  onCancelar: () => void;
  onEnviada: () => void;
  onNotice: (mensaje: string) => void;
};

export function FormularioSugerencia({ original, direccion, traduccionActual, onCancelar, onEnviada, onNotice }: Props) {
  const t = useT();
  const [textoSugerencia, setTextoSugerencia] = useState(traduccionActual);
  const [notaSugerencia, setNotaSugerencia] = useState('');
  const [enviandoSugerencia, setEnviandoSugerencia] = useState(false);

  async function enviarSugerencia() {
    if (!textoSugerencia.trim() || enviandoSugerencia) return;
    setEnviandoSugerencia(true);
    try {
      await postJSON('/api/sugerencias', {
        original,
        traduccion_actual: traduccionActual,
        sugerencia: textoSugerencia.trim(),
        direccion,
        nota: notaSugerencia.trim(),
      }, t('No se pudo enviar la sugerencia.'));
      onNotice(t('¡Gracias! Tu sugerencia quedó pendiente de revisión.'));
      onEnviada();
    } catch (error) {
      onNotice(error instanceof Error ? error.message : t('No se pudo enviar la sugerencia.'));
    } finally {
      setEnviandoSugerencia(false);
    }
  }

  return (
      <div style={{ marginTop: 16, padding: 20, borderRadius: 16, border: '1px solid var(--zl-border-soft)', background: 'var(--zl-surface-soft)', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <p style={{ fontWeight: 700, fontSize: 15, color: 'var(--zl-text)' }}>{t('Sugerir una traducción mejor')}</p>
          <p style={{ fontSize: 13, color: 'var(--zl-text-soft)', marginTop: 2 }}>
            «{original.length > 80 ? original.slice(0, 80) + '…' : original}» · {t('Tu propuesta se revisa antes de agregarse al diccionario.')}
          </p>
        </div>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 600, color: 'var(--zl-label)' }}>
          {direccion === 'spanish-maya' ? t('Traducción correcta en maya') : t('Traducción correcta en español')}
          <textarea value={textoSugerencia} onChange={(e) => setTextoSugerencia(e.target.value)} maxLength={500} rows={2} autoFocus
            style={{ fontSize: 16, fontWeight: 400, padding: '10px 12px', borderRadius: 10, border: '1px solid var(--zl-border-soft)', background: 'var(--zl-input)', resize: 'vertical', color: 'var(--zl-text)' }} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 600, color: 'var(--zl-label)' }}>
          {t('Nota (opcional)')}
          <input value={notaSugerencia} onChange={(e) => setNotaSugerencia(e.target.value)} maxLength={500} placeholder={t('Ej.: así se dice en mi comunidad, o en qué contexto se usa')}
            style={{ fontSize: 14, fontWeight: 400, padding: '9px 12px', borderRadius: 10, border: '1px solid var(--zl-border-soft)', background: 'var(--zl-input)', color: 'var(--zl-text)' }} />
        </label>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <Button variant="ghost" onClick={onCancelar}>{t('Cancelar')}</Button>
          <Button onClick={enviarSugerencia} disabled={!textoSugerencia.trim() || textoSugerencia.trim() === traduccionActual.trim() || enviandoSugerencia} className="gap-2">
            <Send size={14} /> {enviandoSugerencia ? t('Enviando…') : t('Enviar sugerencia')}
          </Button>
        </div>
      </div>
  );
}
