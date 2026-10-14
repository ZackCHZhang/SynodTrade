// Minimal i18n: English source strings are the keys, other languages map them to translations.
// Translations use plain `{n}` where the English source has `{n|word|words}`.
// A missing translation falls back to the English text. Run `npm run i18n:check` to list gaps.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { zh } from './zh';

export type Lang = 'en' | 'zh';

export const LANGS: { code: Lang; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'zh', label: '中文' },
];

const DICTS: Record<Lang, Record<string, string> | null> = { en: null, zh };
const STORAGE_KEY = 'quant-lang';

function readLang(): Lang {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'en' || v === 'zh') return v;
  } catch {
    /* storage unavailable */
  }
  return 'en';
}

let current: Lang = readLang();

export function getLang(): Lang {
  return current;
}

/** BCP 47 locale for dates and numbers. */
export function locale(): string {
  return current === 'zh' ? 'zh-CN' : 'en-US';
}

type Vars = Record<string, string | number | null | undefined>;

/**
 * Translate an English source string and fill its placeholders from `vars`:
 * `{name}` inserts a value; `{n|day|days}` inserts a number followed by the singular or plural word.
 */
export function t(text: string, vars?: Vars): string {
  const out = DICTS[current]?.[text] ?? text;
  if (!vars) return out;
  return out.replace(/\{(\w+)(?:\|([^|}]*)\|([^}]*))?\}/g, (m, k: string, one?: string, other?: string) => {
    if (!(k in vars)) return m;
    const v = vars[k];
    return one === undefined ? String(v ?? '') : `${v} ${v === 1 ? one : other}`;
  });
}

const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: current, setLang: () => {} });

/**
 * Holds the active language. Children are remounted on change so every `t()` call,
 * including those in module-level helpers, renders in the new language.
 */
export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(current);
  const setLang = useCallback((l: Lang) => {
    current = l;
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
    setLangState(l);
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    document.title = 'SynodTrade';
  }, [lang]);
  const value = useMemo(() => ({ lang, setLang }), [lang, setLang]);
  return (
    <LangContext.Provider value={value}>
      <LangKey key={lang}>{children}</LangKey>
    </LangContext.Provider>
  );
}

function LangKey({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function useLang() {
  return useContext(LangContext);
}
