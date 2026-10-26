// Etiqueta que indica de dónde salió cada traducción, para que el
// usuario sepa cuánto confiar en ella. Los colores vienen de variables
// CSS (--zl-fuente-*), que cambian con el modo oscuro.
import { tx, useT } from '@/lib/preferencias';

export type Fuente = 'verificado' | 'referencia' | 'historico' | 'automatico' | 'error';

const FUENTES: Record<Exclude<Fuente, 'error'>, { texto: string; ayuda: string }> = {
  verificado: { texto: tx('✓ Verificada'), ayuda: tx('Revisada a mano en el diccionario del proyecto.') },
  referencia: { texto: tx('Obra de referencia'), ayuda: tx('Viene de diccionarios publicados de maya moderno (como los del INALI o el INEA).') },
  historico: { texto: tx('Fuente histórica'), ayuda: tx('Viene de vocabularios coloniales: la escritura puede ser distinta a la del maya moderno.') },
  automatico: { texto: tx('Traducción automática'), ayuda: tx('Generada por Azure Translator. Puede tener errores; si conoces la correcta, sugiérela.') },
};

export function EtiquetaFuente({ fuente, compacta = false }: { fuente?: Fuente | null; compacta?: boolean }) {
  const t = useT();
  if (!fuente || fuente === 'error') return null;
  const info = FUENTES[fuente];
  return (
    <span title={t(info.ayuda)} style={{
      display: 'inline-flex', alignItems: 'center', fontSize: compacta ? 10 : 12, fontWeight: 600,
      padding: compacta ? '1px 7px' : '3px 10px', borderRadius: 999, whiteSpace: 'nowrap',
      background: `var(--zl-fuente-${fuente}-bg)`, color: `var(--zl-fuente-${fuente}-fg)`,
    }}>
      {t(info.texto)}
    </span>
  );
}
