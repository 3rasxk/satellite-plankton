/**
 * The closed status vocabulary (dashboard spec §5 `StatusChip`) and the only
 * functions allowed to map API status strings onto it.
 *
 * Data source: API status fields, untouched --
 *   - `/raster-scan/pixel` `state` (RasterPixelResponse.state),
 *   - `/risk-map` feature `properties.status`, `stale`, `risk_level`
 *     (RiskMapProperties),
 *   - anomaly `level` / `signal_anomaly_level` / pin `anomaly_level`
 *     (TEST baseline only; test-baseline spec §5).
 *
 * Rules:
 *   - A status string this module has never seen is "no usable data",
 *     never "measured": an unknown must not read as a reading.
 *   - A chip is `{key, tone, hatch, icon}` and nothing else. It carries no
 *     colour and no risk semantics: tones are abstract emphasis levels the
 *     stylesheet maps to neutral greys/ink (the `--risk-*` tokens stay
 *     unused), `hatch` marks an anomaly level so colour is never the only
 *     carrier, and the words come from i18n `status.<key>`.
 *   - There is no risk-tier chip. While risk evaluation is inactive the API
 *     sends `risk_level: null`; a site with a reading then gets a separate
 *     "risk not evaluated" note. A future non-null tier is not rendered here.
 *
 * Limitations: labels only. This module never decides what a reading means.
 */

export const STATUS = Object.freeze({
  MEASURED: 'measured',
  NOT_MEASURED: 'not_measured',
  OUTSIDE_STUDY_AREA: 'outside_study_area',
  NO_USABLE_DATA: 'no_usable_data',
  NOT_CHECKED_YET: 'not_checked_yet',
  NOT_EVALUATED: 'not_evaluated',
  STALE: 'stale',
})

/** Emphasis levels, weakest last. No colour names on purpose. */
export const TONES = Object.freeze(['neutral', 'attention', 'strong', 'muted'])

/** `/raster-scan/pixel` states, as RasterPixelResponse.state lists them. */
export const PIXEL_STATES = Object.freeze(['reading', 'not_measured', 'outside_study_area'])

/** `/risk-map` site statuses, as RiskMapProperties.status lists them. */
export const SITE_STATUSES = Object.freeze([
  'ok', 'no_imagery', 'no_water_pixels', 'no_climatology', 'error', 'no_data_yet',
])

/** Anomaly levels the API can send (RasterPixelAnomaly.level). */
export const ANOMALY_LEVELS = Object.freeze(['normal', 'watch', 'high'])

/** Every anomaly chip key; each has text under `status.<key>`. */
export const ANOMALY_CHIP_KEYS = Object.freeze([
  'anomaly_normal', 'anomaly_watch', 'anomaly_high', 'anomaly_not_assessed',
  'anomaly_normal_test', 'anomaly_watch_test', 'anomaly_high_test', 'anomaly_not_assessed_test',
])

// Presentation of each status chip. Icons are generic glyph names the UI
// maps to SVGs; they are a second carrier beside the text, never the only one.
const STATUS_SPEC = Object.freeze({
  measured: Object.freeze({ tone: 'neutral', hatch: false, icon: 'check' }),
  not_measured: Object.freeze({ tone: 'muted', hatch: false, icon: 'dash' }),
  outside_study_area: Object.freeze({ tone: 'muted', hatch: false, icon: 'boundary' }),
  no_usable_data: Object.freeze({ tone: 'muted', hatch: false, icon: 'slash' }),
  not_checked_yet: Object.freeze({ tone: 'muted', hatch: false, icon: 'clock' }),
  not_evaluated: Object.freeze({ tone: 'muted', hatch: false, icon: 'minus' }),
  stale: Object.freeze({ tone: 'attention', hatch: false, icon: 'history' }),
})

const ANOMALY_SPEC = Object.freeze({
  normal: Object.freeze({ tone: 'neutral', hatch: false, icon: 'baseline' }),
  watch: Object.freeze({ tone: 'attention', hatch: true, icon: 'arrow-up' }),
  high: Object.freeze({ tone: 'strong', hatch: true, icon: 'arrow-up-double' }),
  not_assessed: Object.freeze({ tone: 'muted', hatch: false, icon: 'dash' }),
})

const PIXEL_TO_STATUS = Object.freeze({
  reading: STATUS.MEASURED,
  not_measured: STATUS.NOT_MEASURED,
  outside_study_area: STATUS.OUTSIDE_STUDY_AREA,
})

// A fresh object every time, so a caller mutating a chip cannot change the
// vocabulary for everyone else.
function chip(key) {
  const spec = STATUS_SPEC[key]
  return { key, tone: spec.tone, hatch: spec.hatch, icon: spec.icon }
}

/** The chip for one STATUS value itself (e.g. STALE on a data block, or a
 * count row labelled "no usable data"). Unknown -> no usable data. */
export function chipForStatus(key) {
  return chip(typeof key === 'string' && Object.hasOwn(STATUS_SPEC, key) ? key : STATUS.NO_USABLE_DATA)
}

/** Chip for a `/raster-scan/pixel` `state`. Unknown -> no usable data. */
export function chipForPixelState(state) {
  const key = typeof state === 'string' && Object.hasOwn(PIXEL_TO_STATUS, state)
    ? PIXEL_TO_STATUS[state]
    : STATUS.NO_USABLE_DATA
  return chip(key)
}

/**
 * Chips for one monitoring site: a primary status chip, then notes.
 * Accepts a `/risk-map` feature or its `properties`.
 *   ok          -> measured (+ not_evaluated while risk_level is null)
 *   no_data_yet -> not_checked_yet
 *   anything else, including an unknown string -> no_usable_data
 *   stale: true -> + stale
 */
export function chipForSite(input) {
  let props = input !== null && typeof input === 'object' ? input : {}
  if (props.type === 'Feature') {
    props = props.properties !== null && typeof props.properties === 'object' ? props.properties : {}
  }
  const chips = []
  if (props.status === 'ok') {
    chips.push(chip(STATUS.MEASURED))
    if (props.risk_level === null || props.risk_level === undefined) chips.push(chip(STATUS.NOT_EVALUATED))
  } else if (props.status === 'no_data_yet') {
    chips.push(chip(STATUS.NOT_CHECKED_YET))
  } else {
    chips.push(chip(STATUS.NO_USABLE_DATA))
  }
  if (props.stale === true) chips.push(chip(STATUS.STALE))
  return chips
}

/**
 * Chip for an anomaly level against a location's own history.
 * `normal|watch|high`; anything else (null, unknown) is "not assessed",
 * never "normal". With `isTest` every key ends in `_test`, whose text
 * carries the "(TEST)" marker in both languages.
 */
export function chipForAnomalyLevel(level, isTest) {
  const base = typeof level === 'string' && ANOMALY_LEVELS.includes(level) ? level : 'not_assessed'
  const spec = ANOMALY_SPEC[base]
  const key = `anomaly_${base}${isTest ? '_test' : ''}`
  return { key, tone: spec.tone, hatch: spec.hatch, icon: spec.icon }
}
