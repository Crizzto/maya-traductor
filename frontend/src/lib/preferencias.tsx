// Preferencias del visitante: tema (claro/oscuro) e idioma de la interfaz
// (español/maya). Se guardan en el navegador para recordarlas en la
// siguiente visita.
//
// Traducción de la interfaz: cada texto visible se escribe en español
// dentro de t('...'). En modo maya, t() busca ese texto en
// src/i18n/yua.json y, si no lo encuentra, muestra el español. Ese archivo
// lo genera backend/traducir_interfaz.py con el mismo motor del traductor,
// y se puede corregir a mano.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import textosMaya from '@/i18n/yua.json';

export type Tema = 'claro' | 'oscuro';
export type Idioma = 'es' | 'yua';

const CLAVE_TEMA = 'zacilingua:tema';
const CLAVE_IDIOMA = 'zacilingua:idioma';
const traducciones = textosMaya as Record<string, string>;

type Preferencias = {
  tema: Tema;
  cambiarTema: () => void;
  idioma: Idioma;
  cambiarIdioma: (idioma: Idioma) => void;
  t: (texto: string) => string;
};

const Contexto = createContext<Preferencias | null>(null);

function leer(clave: string): string | null {
  try { return window.localStorage.getItem(clave); } catch { return null; }
}

function guardar(clave: string, valor: string) {
  try { window.localStorage.setItem(clave, valor); } catch { /* modo privado: no se recuerda, sin problema */ }
}

// Script que va en el <head> y corre ANTES de pintar la página, para que
// quien prefiere el modo oscuro no vea un destello blanco al entrar.
export const SCRIPT_TEMA_INICIAL = `(function(){try{var t=localStorage.getItem('${CLAVE_TEMA}');if(!t){t=matchMedia('(prefers-color-scheme: dark)').matches?'oscuro':'claro'}if(t==='oscuro'){document.documentElement.classList.add('dark')}var i=localStorage.getItem('${CLAVE_IDIOMA}');if(i==='yua'){document.documentElement.lang='yua'}}catch(e){}})();`;

export function PreferenciasProvider({ children }: { children: ReactNode }) {
  // En el servidor no hay navegador: se arranca en claro/español y, al
  // cargar en el navegador, se toma lo que el visitante tenía guardado.
  const [tema, setTema] = useState<Tema>('claro');
  const [idioma, setIdioma] = useState<Idioma>('es');

  useEffect(() => {
    setTema(document.documentElement.classList.contains('dark') ? 'oscuro' : 'claro');
    if (leer(CLAVE_IDIOMA) === 'yua') setIdioma('yua');
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', tema === 'oscuro');
    document.documentElement.style.colorScheme = tema === 'oscuro' ? 'dark' : 'light';
  }, [tema]);

  useEffect(() => {
    document.documentElement.lang = idioma;
  }, [idioma]);

  const cambiarTema = useCallback(() => {
    setTema((actual) => {
      const nuevo = actual === 'oscuro' ? 'claro' : 'oscuro';
      guardar(CLAVE_TEMA, nuevo);
      return nuevo;
    });
  }, []);

  const cambiarIdioma = useCallback((nuevo: Idioma) => {
    guardar(CLAVE_IDIOMA, nuevo);
    setIdioma(nuevo);
  }, []);

  const t = useCallback(
    (texto: string) => (idioma === 'yua' ? traducciones[texto] || texto : texto),
    [idioma],
  );

  const valor = useMemo(() => ({ tema, cambiarTema, idioma, cambiarIdioma, t }), [tema, cambiarTema, idioma, cambiarIdioma, t]);
  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function usePreferencias(): Preferencias {
  const contexto = useContext(Contexto);
  if (!contexto) throw new Error('usePreferencias debe usarse dentro de <PreferenciasProvider>.');
  return contexto;
}

// Marca textos que se traducen más tarde con t() (por ejemplo, los que
// viven en listas fuera de los componentes). No hace nada en sí: solo
// sirve para que backend/traducir_interfaz.py los encuentre.
export const tx = (texto: string) => texto;

// Atajo para los componentes que solo necesitan traducir textos.
export function useT() {
  return usePreferencias().t;
}
