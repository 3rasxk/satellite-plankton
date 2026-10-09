/**
 * encodeView / decodeView: a URL query that reopens the exact view a judge
 * saw (dashboard spec §4.2 permalink, §4.6 `?pin=k&run=`).
 *
 * Data source: the view state only -- map centre (lat, lng), raster run,
 * layer, zoom, selected pin rank and language. Nothing else is ever written,
 * so no personal data can travel in a shared link.
 *
 * The decoder is an input boundary (anyone can paste a URL): each key is
 * validated on its own and dropped when invalid, never trusted and never
 * thrown on. Numbers must be plain decimals (no exponent, hex, whitespace or
 * "Infinity"); lat/lng travel only as a valid pair.
 *
 * Limitations: a permalink names a run id; it does not freeze the data. If
 * that run's stored cells expire, the server answers 404 for it.
 */
import { SUPPORTED } from '../i18n/index.js'

/** Query keys, in the order encodeView writes them. */
export const VIEW_PARAMS = Object.freeze(['lat', 'lng', 'run', 'layer', 'zoom', 'pin', 'lang'])

/** Raster layers the map can show (RasterLayerSwitcher modes). */
export const LAYERS = Object.freeze(['ndci', 'light_map', 'true_color'])

export const ZOOM_MIN = 0
export const ZOOM_MAX = 22
export const PIN_MIN = 1
export const PIN_MAX = 10 // highlights `n` is 3-10, so ranks run 1..10

const COORD_DECIMALS = 6 // ~0.1 m: finer than any cell
const ZOOM_DECIMALS = 2

const DECIMAL_RE = /^-?\d+(\.\d+)?$/
const INTEGER_RE = /^\d+$/

const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
const validLat = (v) => isNum(v) && v >= -90 && v <= 90
const validLng = (v) => isNum(v) && v >= -180 && v <= 180
const validRun = (v) => Number.isSafeInteger(v) && v > 0
const validZoom = (v) => isNum(v) && v >= ZOOM_MIN && v <= ZOOM_MAX
const validPin = (v) => Number.isInteger(v) && v >= PIN_MIN && v <= PIN_MAX
const validLayer = (v) => typeof v === 'string' && LAYERS.includes(v)
const validLang = (v) => typeof v === 'string' && SUPPORTED.includes(v)

// Round, then print without trailing zeros or "-0".
const rounded = (v, decimals) => String(Number(v.toFixed(decimals)) + 0)

/**
 * View -> query string (no leading "?"). Accepts
 * `{lat, lng, runId, layer, zoom, pin, lang}`; invalid or unknown values are
 * left out rather than written.
 */
export function encodeView(view) {
  const v = view !== null && typeof view === 'object' ? view : {}
  const pairs = []
  if (validLat(v.lat) && validLng(v.lng)) {
    pairs.push(['lat', rounded(v.lat, COORD_DECIMALS)], ['lng', rounded(v.lng, COORD_DECIMALS)])
  }
  if (validRun(v.runId)) pairs.push(['run', String(v.runId)])
  if (validLayer(v.layer)) pairs.push(['layer', v.layer])
  if (validZoom(v.zoom)) pairs.push(['zoom', rounded(v.zoom, ZOOM_DECIMALS)])
  if (validPin(v.pin)) pairs.push(['pin', String(v.pin)])
  if (validLang(v.lang)) pairs.push(['lang', v.lang])
  return new URLSearchParams(pairs).toString()
}

const decimal = (s) => (typeof s === 'string' && DECIMAL_RE.test(s) ? Number(s) : null)
const integer = (s) => (typeof s === 'string' && INTEGER_RE.test(s) ? Number(s) : null)

/**
 * Query string ("?a=1", "a=1") or URLSearchParams -> view object with only
 * the keys that validated: `{lat, lng, runId, layer, zoom, pin, lang}`.
 */
export function decodeView(search) {
  let params
  if (search instanceof URLSearchParams) params = search
  else if (typeof search === 'string') {
    try {
      params = new URLSearchParams(search)
    } catch {
      return {}
    }
  } else return {}

  const view = {}
  const lat = decimal(params.get('lat'))
  const lng = decimal(params.get('lng'))
  if (validLat(lat) && validLng(lng)) {
    view.lat = lat
    view.lng = lng
  }
  const run = integer(params.get('run'))
  if (validRun(run)) view.runId = run
  const layer = params.get('layer')
  if (validLayer(layer)) view.layer = layer
  const zoom = decimal(params.get('zoom'))
  if (validZoom(zoom)) view.zoom = zoom
  const pin = integer(params.get('pin'))
  if (validPin(pin)) view.pin = pin
  const lang = params.get('lang')
  if (validLang(lang)) view.lang = lang
  return view
}
