import type { ReactNode } from 'react';

// Muestra el formato básico que usa Gemini (**negritas**, *cursivas*,
// listas con "*", "-" o "1.") sin depender de librerías ni insertar HTML
// crudo: todo se arma como elementos de React, así que es seguro.
function formatoEnLinea(texto: string, clave: string) {
  const piezas = texto.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g);
  return piezas.map((pieza, i) => {
    if (/^\*\*[^*]+\*\*$/.test(pieza)) return <strong key={`${clave}-${i}`}>{pieza.slice(2, -2)}</strong>;
    if (/^(\*|_).+(\*|_)$/.test(pieza) && pieza.length > 2) return <em key={`${clave}-${i}`}>{pieza.slice(1, -1)}</em>;
    return pieza;
  });
}

export function TextoMarkdown({ texto }: { texto: string }) {
  const lineas = texto.replace(/\r/g, '').split('\n');
  const bloques: ReactNode[] = [];
  let lista: { ordenada: boolean; items: string[] } | null = null;
  let parrafo: string[] = [];

  const cerrarParrafo = () => {
    if (!parrafo.length) return;
    const k = `p${bloques.length}`;
    bloques.push(<p key={k} style={{ margin: 0 }}>{formatoEnLinea(parrafo.join(' '), k)}</p>);
    parrafo = [];
  };
  const cerrarLista = () => {
    if (!lista) return;
    const k = `l${bloques.length}`;
    const Etiqueta = lista.ordenada ? 'ol' : 'ul';
    bloques.push(
      <Etiqueta key={k} style={{ margin: 0, paddingLeft: 22, listStyle: lista.ordenada ? 'decimal' : 'disc', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {lista.items.map((item, i) => <li key={i}>{formatoEnLinea(item, `${k}-${i}`)}</li>)}
      </Etiqueta>
    );
    lista = null;
  };

  for (const linea of lineas) {
    const limpia = linea.trim();
    const viñeta = limpia.match(/^[*\-•]\s+(.*)$/);
    const numero = limpia.match(/^\d+[.)]\s+(.*)$/);
    const titulo = limpia.match(/^#{1,6}\s+(.*)$/);
    if (!limpia) { cerrarParrafo(); cerrarLista(); continue; }
    if (viñeta || numero) {
      cerrarParrafo();
      const ordenada = Boolean(numero);
      if (lista && lista.ordenada !== ordenada) cerrarLista();
      if (!lista) lista = { ordenada, items: [] };
      lista.items.push((viñeta ?? numero)![1]);
      continue;
    }
    cerrarLista();
    if (titulo) {
      cerrarParrafo();
      const k = `h${bloques.length}`;
      bloques.push(<p key={k} style={{ margin: 0, fontWeight: 700 }}>{formatoEnLinea(titulo[1], k)}</p>);
      continue;
    }
    parrafo.push(limpia);
  }
  cerrarParrafo();
  cerrarLista();
  return <div style={{ lineHeight: 1.55, display: 'flex', flexDirection: 'column', gap: 8 }}>{bloques}</div>;
}
