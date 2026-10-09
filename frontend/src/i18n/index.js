/**
 * Language choice and the translation function every page goes through.
 *
 * Data source: the two static dictionaries next to this file (th.js, en.js).
 * No React here, so it runs under `node --test` (dashboard spec §8, §9).
 *
 * Language priority: `?lang=th|en` in the URL, then the stored choice
 * (`localStorage['plankton.lang']`, read inside try/catch because storage
 * can throw in private windows or when blocked), then Thai. The browser
 * language is deliberately NOT consulted: the default audience is Thai
 * agency staff, and an English browser must not silently switch it.
 *
 * Limitations: `t()` interpolates `{name}` placeholders only -- no plurals,
 * no number formatting (format numbers with src/lib/format.js first and pass
 * the text). A null/undefined/NaN param renders as "—", never "null" or "0";
 * a param the caller forgot stays visible as `{name}` so the gap is noticed.
 */
import th from './th.js'
import en from './en.js'
import { NULL_TEXT } from '../lib/format.js'

export const SUPPORTED = Object.freeze(['th', 'en'])
export const DEFAULT_LANG = 'th'
export const STORAGE_KEY = 'plankton.lang'

const DICTIONARIES = Object.freeze({ th, en })

/** Keys that were asked for but have no text in the chosen dictionary (tests read it). */
export const missingKeys = new Set()

/** 'th' | 'en' for a supported code (any case), else null. */
export function normaliseLang(value) {
  if (typeof value !== 'string') return null
  const code = value.trim().toLowerCase()
  return SUPPORTED.includes(code) ? code : null
}

function langFromSearch(search) {
  if (search === null || search === undefined) return null
  try {
    const params = search instanceof URLSearchParams ? search : new URLSearchParams(String(search))
    return normaliseLang(params.get('lang'))
  } catch {
    return null
  }
}

function langFromStorage(storage) {
  if (!storage) return null
  try {
    return typeof storage.getItem === 'function' ? normaliseLang(storage.getItem(STORAGE_KEY)) : null
  } catch {
    return null
  }
}

/**
 * Pick the language: `?lang=` > storage > Thai.
 * Accepts `{search, storage, navigatorLang}`; `navigatorLang` is accepted for
 * call-site symmetry and intentionally ignored (see module docstring).
 */
export function detectLang(options) {
  const { search, storage } = options !== null && typeof options === 'object' ? options : {}
  return langFromSearch(search) ?? langFromStorage(storage) ?? DEFAULT_LANG
}

/** Store the choice; false when storage is unavailable or refuses. */
export function saveLang(storage, lang) {
  const code = normaliseLang(lang)
  if (!code || !storage) return false
  try {
    storage.setItem(STORAGE_KEY, code)
    return true
  } catch {
    return false
  }
}

function lookup(dict, key) {
  if (typeof key !== 'string' || key === '') return undefined
  let node = dict
  for (const part of key.split('.')) {
    if (node === null || typeof node !== 'object' || !Object.hasOwn(node, part)) return undefined
    node = node[part]
  }
  return typeof node === 'string' ? node : undefined
}

function paramText(value) {
  if (value === null || value === undefined) return NULL_TEXT
  if (typeof value === 'number' && !Number.isFinite(value)) return NULL_TEXT
  return String(value)
}

/** Fill `{name}` placeholders; unknown names are left as written. */
export function interpolate(template, params) {
  const p = params !== null && typeof params === 'object' ? params : {}
  return template.replace(/\{(\w+)\}/g, (whole, name) => (Object.hasOwn(p, name) ? paramText(p[name]) : whole))
}

/**
 * A translation function for `lang` (unsupported -> Thai). `t(key, params)`
 * returns the dictionary text, or -- for a missing key -- the key itself,
 * recording it in `missingKeys`. It never throws. `t.lang` is the language
 * actually used.
 */
export function createT(lang) {
  const resolved = normaliseLang(lang) ?? DEFAULT_LANG
  const dict = DICTIONARIES[resolved]
  const t = (key, params) => {
    const template = lookup(dict, key)
    if (template === undefined) {
      missingKeys.add(String(key))
      return typeof key === 'string' ? key : ''
    }
    return interpolate(template, params)
  }
  t.lang = resolved
  return t
}
