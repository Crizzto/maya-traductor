// Formulario para proponer una traducción mejor. La sugerencia queda
// pendiente de revisión en el backend (no cambia nada hasta aprobarla
// con revisar_sugerencias.py).
import { useState } from 'react';
import { Send } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { postJSON } from '@/lib/api';

type Props = {
  original: string;
  direccion: string;
  traduccionActual: string;
  onCancelar: () => void;
  onEnviada: () => void;
  onNotice: (mensaje: string) => void;
};

export function FormularioSugerencia({ original, direccion, traduccionActual, onCancelar, onEnviada, onNotice }: Props) {
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
      }, 'No se pudo enviar la sugerencia.');
      onNotice('¡Gracias! Tu sugerencia quedó pendiente de revisión.');
      onEnviada();
    } catch (error) {
      onNotice(error instanceof Error ? error.message : 'No se pudo enviar la sugerencia.');
    } finally {
      setEnviandoSugerencia(false);
    }
  }

  return (
      <div style={{ marginTop: 16, padding: 20, borderRadius: 16, border: '1px solid #e7e0cf', background: '#fbf8f1', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <p style={{ fontWeight: 700, fontSize: 15, color: '#1c2b22' }}>Sugerir una traducción mejor</p>
          <p style={{ fontSize: 13, color: '#6b6656', marginTop: 2 }}>
            Para «{original.length > 80 ? original.slice(0, 80) + '…' : original}». Tu propuesta se revisa antes de agregarse al diccionario.
          </p>
        </div>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 600, color: '#3d3a30' }}>
          Traducción correcta en {direccion === 'spanish-maya' ? 'maya' : 'español'}
          <textarea value={textoSugerencia} onChange={(e) => setTextoSugerencia(e.target.value)} maxLength={500} rows={2} autoFocus
            style={{ fontSize: 16, fontWeight: 400, padding: '10px 12px', borderRadius: 10, border: '1px solid #ddd5c1', background: '#fff', resize: 'vertical', color: '#1c2b22' }} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 600, color: '#3d3a30' }}>
          Nota (opcional)
          <input value={notaSugerencia} onChange={(e) => setNotaSugerencia(e.target.value)} maxLength={500} placeholder="Ej.: así se dice en mi comunidad, o en qué contexto se usa"
            style={{ fontSize: 14, fontWeight: 400, padding: '9px 12px', borderRadius: 10, border: '1px solid #ddd5c1', background: '#fff', color: '#1c2b22' }} />
        </label>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <Button variant="ghost" onClick={onCancelar}>Cancelar</Button>
          <Button onClick={enviarSugerencia} disabled={!textoSugerencia.trim() || textoSugerencia.trim() === traduccionActual.trim() || enviandoSugerencia} className="gap-2">
            <Send size={14} /> {enviandoSugerencia ? 'Enviando…' : 'Enviar sugerencia'}
          </Button>
        </div>
      </div>
  );
}
