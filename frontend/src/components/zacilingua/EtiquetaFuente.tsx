// Etiqueta que indica de dónde salió cada traducción, para que el
// usuario sepa cuánto confiar en ella.
export type Fuente = 'verificado' | 'referencia' | 'historico' | 'automatico' | 'error';
const FUENTES: Record<Exclude<Fuente, 'error'>, { texto: string; ayuda: string; fondo: string; color: string }> = {
  verificado: { texto: '✓ Verificada', ayuda: 'Revisada a mano en el diccionario del proyecto.', fondo: '#e3f1e6', color: '#1e5631' },
  referencia: { texto: 'Obra de referencia', ayuda: 'Viene de diccionarios publicados de maya moderno (como los del INALI o el INEA).', fondo: '#e2edf6', color: '#1d4e74' },
  historico: { texto: 'Fuente histórica', ayuda: 'Viene de vocabularios coloniales: la escritura puede ser distinta a la del maya moderno.', fondo: '#f6ecd2', color: '#7a5a12' },
  automatico: { texto: 'Traducción automática', ayuda: 'Generada por Azure Translator. Puede tener errores; si conoces la correcta, sugiérela.', fondo: '#ebe8e1', color: '#5b5648' },
};

export function EtiquetaFuente({ fuente, compacta = false }: { fuente?: Fuente | null; compacta?: boolean }) {
  if (!fuente || fuente === 'error') return null;
  const info = FUENTES[fuente];
  return (
    <span title={info.ayuda} style={{ display: 'inline-flex', alignItems: 'center', fontSize: compacta ? 10 : 12, fontWeight: 600, padding: compacta ? '1px 7px' : '3px 10px', borderRadius: 999, background: info.fondo, color: info.color, whiteSpace: 'nowrap' }}>
      {info.texto}
    </span>
  );
}