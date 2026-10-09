/**
 * formatValue: the one place a number or a date becomes display text.
 *
 * Data source: values exactly as the API returned them (backend/src/schemas.py
 * field types). Nothing here is science -- no thresholds, no classification,
 * no z-scores. It only rounds, signs, groups and appends units.
 *
 * Rules it enforces (dashboard spec §2 point 4, §5 `Value`):
 *   - unknown (null, undefined, NaN, ±Infinity, empty string) is "—" with a
 *     reason, never "0" and never blank;
 *   - a measured zero is a zero ("0.000"), never "—";
 *   - negatives use U+2212 MINUS SIGN, and a value that rounds to zero is
 *     never shown as "minus zero";
 *   - dates are ISO `YYYY-MM-DD` in UTC; times are `YYYY-MM-DD HH:MMZ` in
 *     UTC. A timestamp without an offset is read as UTC (the API's own
 *     convention), never as the viewer's local time.
 * Tabular digits are a CSS concern (`font-variant-numeric`), not done here.
 *
 * Limitations: formatting only. Locale-independent on purpose (a comma
 * thousands separator and a dot decimal in both languages), so a number
 * reads the same in every browser, in tests and in a CSV.
 */

// Written as escapes so an editor cannot silently turn them into ASCII.
export const NULL_TEXT = '—' // EM DASH: the unknown mark
export const MINUS = '−' // MINUS SIGN
export const NBSP = ' ' // NO-BREAK SPACE between a number and its unit
export const EN_DASH = '–' // EN DASH in date spans
const MG_PER_M3 = `mg${NBSP}m⁻³` // mg m⁻³

/** Every value kind formatValue knows. */
export const KINDS = Object.freeze([
  'index', 'fraction', 'percent', 'count', 'date', 'datetime-utc', 'coord', 'ms', 'mg-m3', 'z',
])

/**
 * Reasons a value may be unknown. Each has text under `reason.<code>` in
 * both dictionaries. The first two are produced here; the rest are API
 * status/reason codes (backend/src/schemas.py: RiskMapProperties.status,
 * signal_anomaly_reason, RasterPixelAnomaly.reason, pixel `state`) so the
 * UI can say *why* a value is "—". An API code not listed here is shown
 * verbatim, as server text.
 */
export const NULL_REASONS = Object.freeze([
  'not_available',
  'invalid_value',
  'not_measured',
  'outside_study_area',
  'no_usable_data',
  'not_checked_yet',
  'no_imagery',
  'no_water_pixels',
  'no_climatology',
  'error',
  'no_data_yet',
  'not_evaluated',
  'no_baseline',
  'insufficient_dates',
  'insufficient_independent_dates',
  'zero_mad',
  'incompatible_preprocessing',
  'too_old',
  'not_after_history',
  'low_signal',
  'invalid',
  'site_not_in_baseline',
  'not_assessed_against_active_baseline',
  'no_cached_reading_yet',
  'baseline_invalid',
  'unreadable_band',
])

/** The i18n key for a reason code, or null when the code is not one of
 * NULL_REASONS (then the caller shows the API's code verbatim). Codes of the
 * form `baseline_invalid:<detail>` map on their prefix. */
export function reasonKey(code) {
  if (typeof code !== 'string' || code === '') return null
  const base = code.split(':', 1)[0]
  return NULL_REASONS.includes(base) ? `reason.${base}` : null
}

const DEFAULT_DECIMALS = Object.freeze({
  index: 3, fraction: 2, percent: 1, count: 0, coord: 5, ms: 0, 'mg-m3': 2, z: 2,
})

// Units that attach to the number without a space (12.5°, not 12.5 °):
// degree, prime, double prime.
const TIGHT_UNITS = new Set(['°', '′', '″'])

const MISSING = Symbol('missing')
const INVALID = Symbol('invalid')

const nullResult = (reason) => ({ text: NULL_TEXT, isNull: true, reason })
const valueResult = (text) => ({ text, isNull: false, reason: null })

const NUMERIC_STRING = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/

/** A finite number, MISSING or INVALID. Numeric strings are accepted
 * (some API fields are serialised as text); booleans and objects are not. */
function toNumber(value) {
  if (value === null || value === undefined) return MISSING
  if (typeof value === 'number') return Number.isFinite(value) ? value : MISSING
  if (typeof value === 'string') {
    const s = value.trim()
    if (s === '') return MISSING
    if (!NUMERIC_STRING.test(s)) return INVALID
    const n = Number(s)
    return Number.isFinite(n) ? n : INVALID
  }
  return INVALID
}

function clampDecimals(decimals, fallback) {
  return Number.isInteger(decimals) && decimals >= 0 && decimals <= 20 ? decimals : fallback
}

/** Fixed decimals with U+2212 for negatives; "−0.000" becomes "0.000". */
function signedFixed(num, decimals) {
  let s = num.toFixed(decimals)
  if (/^-0(\.0+)?$/.test(s)) s = s.slice(1)
  return s.startsWith('-') ? MINUS + s.slice(1) : s
}

/** Group the integer part with commas: 1234567.5 -> 1,234,567.5. */
function grouped(fixedText) {
  const negative = fixedText.startsWith(MINUS)
  const body = negative ? fixedText.slice(1) : fixedText
  const [int, frac] = body.split('.')
  const withCommas = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return (negative ? MINUS : '') + withCommas + (frac !== undefined ? `.${frac}` : '')
}

function withUnit(text, unit) {
  if (typeof unit !== 'string' || unit === '') return text
  return TIGHT_UNITS.has(unit) ? `${text}${unit}` : `${text}${NBSP}${unit}`
}

// YYYY-MM-DD, optionally followed by a time and an offset. Python's
// isoformat() writes microseconds and "+00:00"; both are accepted.
const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/

const MAX_EPOCH_MS = 8.64e15

/** Epoch milliseconds (UTC), MISSING or INVALID. */
function toEpochMs(value) {
  if (value === null || value === undefined) return MISSING
  if (value instanceof Date) {
    const t = value.getTime()
    return Number.isFinite(t) ? t : INVALID
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return MISSING
    return Math.abs(value) <= MAX_EPOCH_MS ? value : INVALID
  }
  if (typeof value !== 'string') return INVALID
  const s = value.trim()
  if (s === '') return MISSING
  const m = ISO_RE.exec(s)
  if (!m) return INVALID
  const [, y, mo, d, hh = '00', mi = '00', ss = '00', frac = '', tz] = m
  const year = Number(y)
  const month = Number(mo)
  const day = Number(d)
  const hour = Number(hh)
  const minute = Number(mi)
  const second = Number(ss)
  if (month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) return INVALID
  // Reject dates that do not exist (2026-02-30 would otherwise roll over).
  const check = new Date(Date.UTC(year, month - 1, day))
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) {
    return INVALID
  }
  const millis = frac ? Math.floor(Number(`0${frac}`) * 1000) : 0
  let offsetMinutes = 0
  if (tz && tz !== 'Z') {
    const sign = tz[0] === '-' ? -1 : 1
    const digits = tz.slice(1).replace(':', '')
    const oh = Number(digits.slice(0, 2))
    const om = Number(digits.slice(2, 4))
    if (oh > 23 || om > 59) return INVALID
    offsetMinutes = sign * (oh * 60 + om)
  }
  return Date.UTC(year, month - 1, day, hour, minute, second, millis) - offsetMinutes * 60000
}

/** Epoch milliseconds (UTC) of an ISO date/timestamp, a Date or epoch ms;
 * null when unknown or unparseable. A timestamp without an offset is UTC. */
export function toUtcMs(value) {
  const ms = toEpochMs(value)
  return typeof ms === 'number' ? ms : null
}

function formatTime(value, kind, nullReason) {
  const ms = toEpochMs(value)
  if (ms === MISSING) return nullResult(nullReason)
  if (ms === INVALID) return nullResult('invalid_value')
  const iso = new Date(ms).toISOString()
  if (kind === 'date') return valueResult(iso.slice(0, 10))
  return valueResult(`${iso.slice(0, 10)} ${iso.slice(11, 16)}Z`)
}

/**
 * Format one API value for display.
 *
 * @param {*} value  the API value, untouched
 * @param {{kind?: string, decimals?: number, unit?: string, reason?: string}} spec
 *   `reason` is the reason to report when the value is unknown (default
 *   'not_available'); an unparseable value always reports 'invalid_value'.
 * @returns {{text: string, isNull: boolean, reason: string|null}}
 */
export function formatValue(value, spec) {
  const s = spec !== null && typeof spec === 'object' ? spec : {}
  const kind = typeof s.kind === 'string' ? s.kind : null
  const nullReason = typeof s.reason === 'string' && s.reason ? s.reason : 'not_available'

  if (kind === 'date' || kind === 'datetime-utc') return formatTime(value, kind, nullReason)

  const num = toNumber(value)
  if (num === MISSING) return nullResult(nullReason)
  if (num === INVALID) return nullResult('invalid_value')

  switch (kind) {
    case 'index':
    case 'fraction':
    case 'z':
    case 'coord':
      return valueResult(withUnit(signedFixed(num, clampDecimals(s.decimals, DEFAULT_DECIMALS[kind])), s.unit))
    case 'count':
      return valueResult(withUnit(grouped(signedFixed(num, clampDecimals(s.decimals, 0))), s.unit))
    case 'percent':
      return valueResult(`${signedFixed(num * 100, clampDecimals(s.decimals, DEFAULT_DECIMALS.percent))}${NBSP}%`)
    case 'ms':
      return valueResult(`${signedFixed(num, clampDecimals(s.decimals, 0))}${NBSP}ms`)
    case 'mg-m3':
      return valueResult(`${signedFixed(num, clampDecimals(s.decimals, DEFAULT_DECIMALS['mg-m3']))}${NBSP}${MG_PER_M3}`)
    default: {
      // Unknown kind: the number as given (or at the requested decimals),
      // still with the house minus sign. Never null for a real number.
      const text = Number.isInteger(s.decimals)
        ? signedFixed(num, clampDecimals(s.decimals, 0))
        : String(num).replace(/^-/, MINUS)
      return valueResult(withUnit(text, s.unit))
    }
  }
}

/**
 * "oldest–newest" for a span of ISO dates; one date when both are equal;
 * null when neither is known. An unknown end is "—", never invented.
 */
export function formatDateSpan(oldest, newest) {
  const a = typeof oldest === 'string' && oldest ? oldest : null
  const b = typeof newest === 'string' && newest ? newest : null
  if (!a && !b) return null
  if (a === b) return a
  return `${a ?? NULL_TEXT}${EN_DASH}${b ?? NULL_TEXT}`
}
