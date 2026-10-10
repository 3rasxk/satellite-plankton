/**
 * The language context object and `useLang()` -- `{lang, setLang, t}`.
 *
 * Data source: the providers in ./LangContext.jsx. This file holds only the
 * context and the hook (no components), so Vite fast refresh keeps working
 * for the provider file and lint's only-export-components rule stays quiet.
 *
 * Limitations: outside any provider (a component rendered on its own) the
 * default is Thai with a no-op `setLang` -- never a crash, never English by
 * accident.
 */
import { createContext, useContext } from 'react'
import { DEFAULT_LANG, createT } from './index.js'

export const LangContext = createContext({
  lang: DEFAULT_LANG,
  setLang: () => {},
  t: createT(DEFAULT_LANG),
})

export function useLang() {
  return useContext(LangContext)
}
