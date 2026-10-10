/**
 * Language providers: `LangProvider` for the app, `StaticLangProvider` for
 * tests and isolated renders. Both feed `useLang()` (./useLang.js) with
 * `{lang, setLang, t}`.
 *
 * Data source: the URL (`?lang=th|en`), then the stored choice
 * (`localStorage['plankton.lang']`, guarded), then Thai -- the order
 * `detectLang` in ./index.js defines (dashboard spec §8).
 *
 * Behaviour of `LangProvider` (must sit inside the router):
 *   - a `?lang=` in the current URL wins, so a shared link, back/forward and
 *     a pasted permalink all show the language they name;
 *   - otherwise the last choice made in this session (initially detected)
 *     is used, so moving between pages keeps the language without a reload;
 *   - `setLang(code)` stores the choice (failure ignored: storage can throw
 *     in private windows), rewrites `?lang=` with history `replace` (the
 *     path, other query keys and hash are kept; no reload) and updates
 *     `<html lang>` so screen readers and hyphenation follow.
 *
 * Limitations: two languages only; an unsupported code is ignored.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { createT, detectLang, normaliseLang, saveLang } from './index.js'
import { LangContext } from './useLang.js'

function browserStorage() {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

function langParam(search) {
  try {
    return normaliseLang(new URLSearchParams(search).get('lang'))
  } catch {
    return null
  }
}

export function LangProvider({ children }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [chosen, setChosen] = useState(() => detectLang({ search: location.search, storage: browserStorage() }))
  const lang = langParam(location.search) ?? chosen

  useEffect(() => {
    if (typeof document !== 'undefined') document.documentElement.lang = lang
  }, [lang])

  const { pathname, search, hash, state } = location
  const setLang = useCallback((next) => {
    const code = normaliseLang(next)
    if (!code) return
    setChosen(code)
    saveLang(browserStorage(), code)
    const params = new URLSearchParams(search)
    params.set('lang', code)
    navigate({ pathname, search: `?${params.toString()}`, hash }, { replace: true, state })
  }, [pathname, search, hash, state, navigate])

  const value = useMemo(() => ({ lang, setLang, t: createT(lang) }), [lang, setLang])
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>
}

const noop = () => {}

/** A fixed language with no router and no storage (tests, isolated renders). */
export function StaticLangProvider({ lang, children }) {
  const code = normaliseLang(lang) ?? 'th'
  const value = useMemo(() => ({ lang: code, setLang: noop, t: createT(code) }), [code])
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>
}
