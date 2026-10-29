import { es } from './locales/es'

// UI strings are written in English in the code and looked up in a per-language dictionary
// (gettext style): t('Easy run') renders "Rodaje suave" in Spanish. Missing entries fall back to
// English, so an incomplete translation never breaks the UI. The language is fixed for the
// page's lifetime; switching it reloads the app.

export type Lang = 'en' | 'es'
export const LANGS: [Lang, string][] = [['en', 'English'], ['es', 'Español']]
const DICTS: Record<Lang, Record<string, string> | null> = { en: null, es }
const KEY = 'lang'

const isLang = (x: unknown): x is Lang => x === 'en' || x === 'es'

function detect(): Lang {
  try {
    const saved = localStorage.getItem(KEY)
    if (isLang(saved)) return saved
  } catch {
    /* storage unavailable */
  }
  for (const l of navigator.languages ?? [navigator.language]) {
    const base = l?.slice(0, 2).toLowerCase()
    if (isLang(base)) return base
  }
  return 'en'
}

let lang: Lang = detect()
document.documentElement.lang = lang

export const getLang = () => lang

/** Persist the language and reload so every module-level label is rebuilt. */
export function setLang(l: Lang, reload = true) {
  try { localStorage.setItem(KEY, l) } catch { /* ignore */ }
  if (l === lang) return
  lang = l
  if (reload) window.location.reload()
}

/** BCP 47 locale for dates and numbers. */
export const locale = () => (lang === 'es' ? 'es-ES' : 'en-GB')

/** Translate an English UI string; `{name}` placeholders are filled from `vars`. */
export function t(text: string, vars?: Record<string, string | number>): string {
  const s = DICTS[lang]?.[text] ?? text
  return vars ? s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : s
}
