/**
 * methodsModel: everything the Methods page (`/methods`) shows, as data --
 * formatted values with their field paths and source refs, server texts
 * to show verbatim, i18n keys and the anchors other pages link to -- so
 * the page is a thin renderer and every rule here runs under `node --test`
 * (dashboard spec §4.4, §5; test-baseline spec §3-§5, §7, §8).
 *
 * Data source (read-only; nothing computed that the API did not send):
 *   - `GET /methods` (MethodsResponse, backend/src/schemas.py): index
 *     definitions with worked examples the server computed with its own
 *     functions, Sentinel-2 / MODIS settings, gates and floors, the robust-z
 *     statistic, the latest-scene policy, season windows, the baseline
 *     status (incl. the Level A self-check `base_rates`), the quality
 *     screens and the references, plus the server `disclaimer`;
 *   - `GET /raster-scan/highlights?mode=anomaly` (only while a valid TEST
 *     baseline is in force): its `baseline.level_b` block, the Level B
 *     (per-cell) baseline summary of the season the served run was compared
 *     with. Its failure (e.g. HTTP 409 when no cell baseline can be used)
 *     degrades that block only.
 *
 * Rules kept here:
 *   - every number shown is an API field: each displayed value carries its
 *     `field` path (e.g. `indices[0].worked_example.value`) and a
 *     `sourceRef`; nothing is hard-coded. The only derivations are the two
 *     base-rate shares (watch / assessed, high / assessed), percentages of
 *     API-provided counts, which the dashboard rules allow;
 *   - unknown is "—" with a reason, never 0; a missing wavelength is "not
 *     documented", never invented;
 *   - API free text (notes, rules, citations, formulas) is passed through
 *     verbatim for display as server text;
 *   - the TEST baseline section has content only when `baseline.mode` is
 *     'test'; otherwise it carries the explanation of why it is off. The
 *     section and its `#baseline` anchor exist in every mode, because other
 *     pages link to it;
 *   - no risk tier and no verdict: the gates are restated as the API sends
 *     them.
 *
 * Limitations: pure functions of their inputs; no fetching. Formatting
 * decimals below are display choices, not science.
 */
import { formatValue, NULL_TEXT } from './format.js'
import { sourceRef } from './provenance.js'

export const METHODS_ENDPOINT = '/methods'
export const LEVEL_B_ENDPOINT = '/raster-scan/highlights'
export const LEVEL_B_PARAMS = Object.freeze({ mode: 'anomaly' })

/** The page sections, in display order; each id is also its anchor. */
export const METHODS_SECTIONS = Object.freeze([
  'sources', 'indices', 'quality', 'gates', 'baseline', 'latest_scene', 'references',
])

/** Anchors inside sections that other pages link to (`/methods#…`). The
 * index keys (`indices[].key`) are anchors too, one per IndexCard. */
export const FIXED_ANCHORS = Object.freeze(['sentinel2', 'modis', 'robust_z', 'level_a', 'level_b'])

/** Display text of each index key (scientific symbols, never translated). */
export const INDEX_SYMBOLS = Object.freeze({ ndci: 'NDCI', '2bda': '2BDA', '3bda': '3BDA', b2_b3_ratio: 'B2/B3' })

/** MethodsIndex.role values with a translated label (`methods.role.<role>`). */
export const INDEX_ROLES = Object.freeze(['primary', 'derived', 'comparison', 'exploratory'])

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)
const finite = (v) => typeof v === 'number' && Number.isFinite(v)
const hasValue = (v) => v !== null && v !== undefined
const text = (v) => (typeof v === 'string' && v.trim() !== '' ? v : null)
const list = (v) => (Array.isArray(v) ? v : [])
const msg = (key, params = {}) => ({ key, params })

/** One displayed API value: raw value, spec, formatted text, field path and
 * its source popover. `reason` is the reason code when it is unknown. */
function item(id, labelKey, raw, spec, field, src = {}) {
  const r = formatValue(raw, spec)
  return {
    id,
    labelKey,
    raw: hasValue(raw) ? raw : null,
    spec,
    text: r.text,
    isNull: r.isNull,
    reason: r.reason,
    field,
    source: sourceRef({
      endpoint: src.endpoint ?? METHODS_ENDPOINT,
      field,
      value: raw,
      unit: spec.unit ?? (spec.kind === 'percent' || spec.kind === 'fraction' ? 'fraction' : (spec.kind === 'count' ? 'count' : null)),
      runId: src.runId ?? null,
      params: src.params ?? null,
    }),
  }
}

/** A list value (e.g. SCL classes, season months) as one text, with its source. */
function listItem(id, labelKey, raw, field, src = {}) {
  const values = Array.isArray(raw) ? raw.filter((v) => finite(v) || typeof v === 'string') : null
  return {
    id,
    labelKey,
    raw: values,
    text: values && values.length > 0 ? values.join(', ') : NULL_TEXT,
    isNull: !values || values.length === 0,
    field,
    source: sourceRef({ endpoint: src.endpoint ?? METHODS_ENDPOINT, field, value: raw, params: src.params ?? null, runId: src.runId ?? null }),
  }
}

/** A short API code or identifier (collection id, signature, version). */
function codeItem(id, labelKey, raw, field, src = {}) {
  const value = text(raw)
  return {
    id,
    labelKey,
    raw: value,
    text: value ?? NULL_TEXT,
    isNull: value === null,
    field,
    source: sourceRef({ endpoint: src.endpoint ?? METHODS_ENDPOINT, field, value: raw, params: src.params ?? null, runId: src.runId ?? null }),
  }
}

/** A boolean gate as the API sent it; null when it is not a boolean. */
function boolItem(id, raw, field) {
  const known = typeof raw === 'boolean'
  return {
    id,
    raw: known ? raw : null,
    text: known ? String(raw) : NULL_TEXT,
    isNull: !known,
    stateKey: known ? (raw ? 'methods.gates.active' : 'methods.gates.inactive') : null,
    field,
    source: sourceRef({ endpoint: METHODS_ENDPOINT, field, value: raw }),
  }
}

/** An API free-text field, shown verbatim (null when absent). */
const serverText = (v) => text(v)

// ------------------------------------------------------------- sources

const RES = Object.freeze({ kind: 'count', unit: 'm' })
const NM = Object.freeze({ kind: 'count', unit: 'nm' })
const DAYS = Object.freeze({ kind: 'count', unit: 'd' })
const HOURS = Object.freeze({ kind: 'count', unit: 'h' })
const COUNT = Object.freeze({ kind: 'count' })
const DN = Object.freeze({ kind: 'count', unit: 'DN' })
const PERCENT = Object.freeze({ kind: 'percent', decimals: 0 })
const AS_GIVEN = Object.freeze({})
const DATE = Object.freeze({ kind: 'date' })
const DATETIME = Object.freeze({ kind: 'datetime-utc' })
const DOMAIN = Object.freeze({ kind: 'index', decimals: 2 })
const EXAMPLE_VALUE = Object.freeze({ kind: 'index', decimals: 6 })
const Z_LEVEL = Object.freeze({ kind: 'z', decimals: 1 })
const SHARE = Object.freeze({ kind: 'percent', decimals: 1 })

function sentinel2Model(s2) {
  const s = isObject(s2) ? s2 : {}
  const res = isObject(s.native_resolution_m) ? s.native_resolution_m : {}
  const wl = isObject(s.wavelengths_nm) ? s.wavelengths_nm : {}
  const bands = list(s.bands).filter((b) => typeof b === 'string')
  const scale = item('scale_factor', 'methods.s2.scale_factor', s.scale_factor, COUNT, 'sentinel2.scale_factor')
  return {
    anchor: 'sentinel2',
    collection: codeItem('collection', 'methods.s2.collection', s.collection, 'sentinel2.collection'),
    bands: bands.map((band) => ({
      band,
      resolution: item(`res_${band}`, 'methods.s2.col_resolution', res[band], { ...RES, reason: 'not_available' }, `sentinel2.native_resolution_m.${band}`),
      wavelength: item(`wl_${band}`, 'methods.s2.col_wavelength', Object.hasOwn(wl, band) ? wl[band] : null, NM, `sentinel2.wavelengths_nm.${band}`),
      wavelengthDocumented: Object.hasOwn(wl, band) && finite(wl[band]),
    })),
    bandsSource: sourceRef({ endpoint: METHODS_ENDPOINT, field: 'sentinel2.bands', value: s.bands }),
    wavelengthsNote: serverText(s.wavelengths_note),
    facts: [
      item('revisit_days', 'methods.s2.revisit', s.revisit_days, DAYS, 'sentinel2.revisit_days'),
      scale,
      item('max_scene_age_days', 'methods.s2.max_scene_age', s.max_scene_age_days, DAYS, 'sentinel2.max_scene_age_days'),
    ],
    scaleNote: scale.isNull ? null : msg('methods.s2.scale_note', { scale: scale.text }),
    sceneAgeNote: finite(s.max_scene_age_days)
      ? msg('methods.s2.scene_age_note', { days: formatValue(s.max_scene_age_days, COUNT).text })
      : null,
  }
}

function modisModel(modis) {
  const m = isObject(modis) ? modis : {}
  return {
    anchor: 'modis',
    collection: codeItem('collection', 'methods.modis.collection', m.collection, 'modis.collection'),
    bands: listItem('bands', 'methods.modis.bands', m.bands, 'modis.bands'),
    facts: [
      item('grid_resolution_m', 'methods.modis.grid', m.grid_resolution_m, RES, 'modis.grid_resolution_m'),
      item('record_start', 'methods.modis.record_start', m.record_start, DATE, 'modis.record_start'),
    ],
    note: serverText(m.note),
  }
}

// ------------------------------------------------------------- indices

function indexCard(ix, i) {
  const x = isObject(ix) ? ix : {}
  const key = text(x.key) ?? `index_${i}`
  const base = `indices[${i}]`
  const wl = isObject(x.wavelengths_nm) ? x.wavelengths_nm : {}
  const ex = isObject(x.worked_example) ? x.worked_example : {}
  const exBands = isObject(ex.bands) ? ex.bands : {}
  const bands = list(x.bands).filter((b) => typeof b === 'string')
  const role = text(x.role)
  const domain = isObject(x.display_domain) ? x.display_domain : null
  return {
    key,
    anchor: key,
    symbol: Object.hasOwn(INDEX_SYMBOLS, key) ? INDEX_SYMBOLS[key] : key,
    name: serverText(x.name),
    formula: serverText(x.formula),
    formulaSource: sourceRef({ endpoint: METHODS_ENDPOINT, field: `${base}.formula`, value: x.formula, formulaKey: key }),
    role,
    roleKey: role && INDEX_ROLES.includes(role) ? `methods.role.${role}` : null,
    note: serverText(x.note),
    rasterBand: codeItem('raster_band', 'methods.index.raster_band', x.raster_band, `${base}.raster_band`),
    bands: bands.map((band) => ({
      band,
      wavelength: item(`wl_${band}`, 'methods.index.wavelength', Object.hasOwn(wl, band) ? wl[band] : null, NM, `${base}.wavelengths_nm.${band}`),
      wavelengthDocumented: Object.hasOwn(wl, band) && finite(wl[band]),
    })),
    domain: domain
      ? {
        min: item('domain_min', 'methods.index.domain_min', domain.min, DOMAIN, `${base}.display_domain.min`),
        max: item('domain_max', 'methods.index.domain_max', domain.max, DOMAIN, `${base}.display_domain.max`),
      }
      : null,
    domainSource: sourceRef({ endpoint: METHODS_ENDPOINT, field: `${base}.display_domain`, value: x.display_domain }),
    example: {
      // The bands the index uses, in the API's order, with the sample DN.
      bands: bands.map((band) => ({ band, ...item(`ex_${band}`, null, Object.hasOwn(exBands, band) ? exBands[band] : null, DN, `${base}.worked_example.bands.${band}`) })),
      value: item('ex_value', 'methods.index.example_value', ex.value, { ...EXAMPLE_VALUE, reason: 'invalid_value' }, `${base}.worked_example.value`),
      note: serverText(ex.note),
    },
  }
}

// ------------------------------------------------------------- quality

function qualityModel(s2, screens) {
  const s = isObject(s2) ? s2 : {}
  const q = isObject(screens) ? screens : {}
  const d = isObject(q.degenerate_ndci) ? q.degenerate_ndci : null
  const l = isObject(q.low_signal) ? q.low_signal : null
  return {
    masks: [
      item('max_cloud_fraction', 'methods.quality.max_cloud', s.max_cloud_fraction, PERCENT, 'sentinel2.max_cloud_fraction'),
      listItem('cloud_mask_scl_classes', 'methods.quality.scl_classes', s.cloud_mask_scl_classes, 'sentinel2.cloud_mask_scl_classes'),
      item('min_water_occurrence_pct', 'methods.quality.water_occurrence', s.min_water_occurrence_pct, { unit: '%' }, 'sentinel2.min_water_occurrence_pct'),
    ],
    screens: [
      d && {
        id: 'degenerate_ndci',
        titleKey: 'methods.quality.degenerate_title',
        labelKey: null,
        rule: serverText(d.rule),
        values: [item('threshold_abs', 'methods.quality.threshold_abs', d.threshold_abs, AS_GIVEN, 'quality_screens.degenerate_ndci.threshold_abs')],
        bands: null,
        texts: [
          { id: 'meaning', labelKey: 'methods.quality.meaning', text: serverText(d.meaning) },
          { id: 'effect', labelKey: 'methods.quality.effect', text: serverText(d.effect) },
        ].filter((t) => t.text),
        status: serverText(d.status),
      },
      l && {
        id: 'low_signal',
        titleKey: 'methods.quality.low_signal_title',
        // The brief's binding label: this screen is a developer choice, not validated.
        labelKey: 'methods.quality.not_validated',
        rule: serverText(l.rule),
        values: [
          item('min_visible_dn', 'methods.quality.min_visible_dn', l.min_visible_dn, DN, 'quality_screens.low_signal.min_visible_dn'),
          item('approx_reflectance', 'methods.quality.approx_reflectance', l.approx_reflectance, AS_GIVEN, 'quality_screens.low_signal.approx_reflectance'),
        ],
        bands: listItem('bands', 'methods.quality.bands', l.bands, 'quality_screens.low_signal.bands'),
        texts: [
          { id: 'rationale', labelKey: 'methods.quality.rationale', text: serverText(l.rationale) },
          { id: 'effect', labelKey: 'methods.quality.effect', text: serverText(l.effect) },
        ].filter((t) => t.text),
        status: serverText(l.status),
      },
    ].filter(Boolean),
  }
}

// --------------------------------------------------------------- gates

function gatesModel(gates) {
  const g = isObject(gates) ? gates : {}
  const floors = isObject(g.signal_anomaly_floors) ? g.signal_anomaly_floors : {}
  const st = isObject(g.signal_anomaly_statistic) ? g.signal_anomaly_statistic : {}
  const minDates = item('min_independent_dates', 'methods.gates.min_dates', floors.min_independent_dates, COUNT, 'gates.signal_anomaly_floors.min_independent_dates')
  const maxAge = item('max_observation_age_days', 'methods.gates.max_age', floors.max_observation_age_days, DAYS, 'gates.signal_anomaly_floors.max_observation_age_days')
  const watch = item('watch_at_z', 'methods.stat.watch', st.watch_at_z, Z_LEVEL, 'gates.signal_anomaly_statistic.watch_at_z')
  const high = item('high_at_z', 'methods.stat.high', st.high_at_z, Z_LEVEL, 'gates.signal_anomaly_statistic.high_at_z')
  return {
    rows: [
      { id: 'risk_evaluation_active', meaningKey: 'methods.gates.risk_meaning', value: boolItem('risk_evaluation_active', g.risk_evaluation_active, 'gates.risk_evaluation_active') },
      { id: 'signal_anomaly_active', meaningKey: 'methods.gates.anomaly_meaning', value: boolItem('signal_anomaly_active', g.signal_anomaly_active, 'gates.signal_anomaly_active') },
    ],
    floors: [
      { id: 'min_independent_dates', meaningKey: 'methods.gates.min_dates_meaning', value: minDates },
      { id: 'max_observation_age_days', meaningKey: 'methods.gates.max_age_meaning', value: maxAge },
    ],
    whyNoRisk: msg('methods.gates.why_no_risk', { min_dates: minDates.text, max_age: maxAge.text }),
    statistic: {
      anchor: 'robust_z',
      formula: serverText(st.formula),
      formulaSource: sourceRef({ endpoint: METHODS_ENDPOINT, field: 'gates.signal_anomaly_statistic.formula', value: st.formula }),
      values: [
        item('mad_scale', 'methods.stat.mad_scale', st.mad_scale, AS_GIVEN, 'gates.signal_anomaly_statistic.mad_scale'),
        watch,
        high,
      ],
      levels: msg('methods.stat.levels', { watch: watch.text, high: high.text }),
      note: serverText(st.note),
    },
  }
}

// ------------------------------------------------------------ baseline

function baseRatesModel(rates) {
  const r = isObject(rates) ? rates : null
  if (!r) return null
  const f = 'baseline.base_rates'
  const assessed = item('assessed', 'methods.rates.assessed', r.assessed, COUNT, `${f}.assessed`)
  const watch = item('watch', 'methods.rates.watch', r.watch, COUNT, `${f}.watch`)
  const high = item('high', 'methods.rates.high', r.high, COUNT, `${f}.high`)
  const none = item('no_assessment', 'methods.rates.no_assessment', r.no_assessment, COUNT, `${f}.no_assessment`)
  // Percentages of API-provided counts (allowed derivation); none without a
  // positive denominator.
  const share = (n) => (finite(n) && finite(r.assessed) && r.assessed > 0 ? n / r.assessed : null)
  const watchShare = formatValue(share(r.watch), SHARE)
  const highShare = formatValue(share(r.high), SHARE)
  const reasons = isObject(r.reasons) ? r.reasons : {}
  return {
    counts: [assessed, watch, high, none],
    reasons: Object.keys(reasons).map((code) => ({ code, ...item(`reason_${code}`, null, reasons[code], COUNT, `${f}.reasons.${code}`) })),
    watchShare: { raw: share(r.watch), text: watchShare.text, isNull: watchShare.isNull },
    highShare: { raw: share(r.high), text: highShare.text, isNull: highShare.isNull },
    summary: watchShare.isNull || highShare.isNull
      ? msg('methods.rates.summary_none')
      : msg('methods.rates.summary', { watch: watchShare.text, high: highShare.text, assessed: assessed.text }),
  }
}

/** Level B (per-cell) baseline summary from `/raster-scan/highlights?mode=anomaly`. */
export function buildLevelBModel({ highlights, request } = {}) {
  const req = isObject(request) ? request : {}
  if (req.error) return { state: 'error', error: req.error, endpoint: `${LEVEL_B_ENDPOINT}?mode=anomaly` }
  if (req.loading || !isObject(highlights)) return { state: 'loading' }
  const lb = isObject(highlights.baseline) && isObject(highlights.baseline.level_b) ? highlights.baseline.level_b : null
  if (!lb) return { state: 'empty', key: 'methods.level_b.none' }
  const src = { endpoint: LEVEL_B_ENDPOINT, params: LEVEL_B_PARAMS, runId: highlights.run_id ?? null }
  const f = (name) => `baseline.level_b.${name}`
  const v = (id, labelKey, spec) => item(id, labelKey, lb[id], spec, f(id), src)
  return {
    state: 'ready',
    endpoint: `${LEVEL_B_ENDPOINT}?mode=anomaly`,
    runId: highlights.run_id ?? null,
    season: codeItem('season_key', 'methods.level_b.season_key', lb.season_key, f('season_key'), src),
    months: listItem('months', 'methods.level_b.months', lb.months, f('months'), src),
    facts: [
      v('scale_m', 'methods.level_b.scale_m', RES),
      v('history_start', 'methods.level_b.history_start', DATE),
      v('history_end', 'methods.level_b.history_end', DATE),
      v('first_date', 'methods.level_b.first_date', DATE),
      v('last_date', 'methods.level_b.last_date', DATE),
      v('n_dates', 'methods.level_b.n_dates', COUNT),
      v('min_independent_dates', 'methods.level_b.min_dates', COUNT),
      v('max_observation_age_days', 'methods.level_b.max_age', DAYS),
      v('cells', 'methods.level_b.cells', COUNT),
      v('cells_n_ge_floor', 'methods.level_b.cells_ge_floor', COUNT),
      v('share_n_ge_floor', 'methods.level_b.share_ge_floor', SHARE),
      v('n_min', 'methods.level_b.n_min', COUNT),
      v('n_median', 'methods.level_b.n_median', AS_GIVEN),
      v('n_max', 'methods.level_b.n_max', COUNT),
      v('mad_p05', 'methods.level_b.mad_p05', { kind: 'index', decimals: 4 }),
      v('mad_p50', 'methods.level_b.mad_p50', { kind: 'index', decimals: 4 }),
      v('mad_p95', 'methods.level_b.mad_p95', { kind: 'index', decimals: 4 }),
      v('built_at', 'methods.level_b.built_at', DATETIME),
    ],
    signature: codeItem('cell_preprocessing_signature', 'methods.level_b.signature', lb.cell_preprocessing_signature, f('cell_preprocessing_signature'), src),
    historyEndRule: serverText(lb.history_end_rule),
    seasonRule: serverText(lb.season_rule),
  }
}

function baselineModel(methods, levelB) {
  const b = isObject(methods.baseline) ? methods.baseline : null
  const mode = b && (b.mode === 'test' || b.mode === 'off') ? b.mode : null
  if (mode === 'off') return { anchor: 'baseline', state: 'off', explanationKey: 'methods.baseline.off' }
  if (mode !== 'test') return { anchor: 'baseline', state: 'unknown', explanationKey: 'methods.baseline.unknown' }
  if (b.valid !== true) {
    return {
      anchor: 'baseline',
      state: 'invalid',
      explanationKey: 'methods.baseline.invalid',
      reason: serverText(b.reason),
    }
  }
  const perSite = isObject(b.min_season_dates_by_location) ? b.min_season_dates_by_location : {}
  return {
    anchor: 'baseline',
    state: 'test',
    intro: msg('methods.baseline.intro', {
      start: formatValue(b.history_start, DATE).text,
      end: formatValue(b.history_end, DATE).text,
    }),
    version: codeItem('version', 'methods.baseline.version', b.version, 'baseline.version'),
    facts: [
      item('built_at', 'methods.baseline.built_at', b.built_at, DATETIME, 'baseline.built_at'),
      item('history_start', 'methods.baseline.history_start', b.history_start, DATE, 'baseline.history_start'),
      item('history_end', 'methods.baseline.history_end', b.history_end, DATE, 'baseline.history_end'),
      item('min_independent_dates', 'methods.baseline.min_dates', b.min_independent_dates, COUNT, 'baseline.min_independent_dates'),
      item('median_independent_dates', 'methods.baseline.median_dates', b.median_independent_dates, AS_GIVEN, 'baseline.median_independent_dates'),
    ],
    signature: codeItem('preprocessing_signature', 'methods.baseline.signature', b.preprocessing_signature, 'baseline.preprocessing_signature'),
    seasonRule: serverText(methods.season_rule) ?? serverText(b.season_rule),
    seasonRuleSource: sourceRef({ endpoint: METHODS_ENDPOINT, field: 'season_rule', value: methods.season_rule }),
    seasonWindows: list(methods.season_windows).filter(isObject).map((w, i) => ({
      month: item(`month_${i}`, null, w.month, COUNT, `season_windows[${i}].month`),
      key: text(w.key) ?? NULL_TEXT,
      months: listItem(`months_${i}`, null, w.months, `season_windows[${i}].months`),
    })),
    perSite: Object.keys(perSite).map((site) => ({
      site,
      count: item(`site_${site}`, null, perSite[site], COUNT, `baseline.min_season_dates_by_location.${site}`),
    })),
    rates: baseRatesModel(b.base_rates),
    levelB: levelB ?? { state: 'loading' },
  }
}

// --------------------------------------------------------- latest scene

function latestSceneModel(policy) {
  const p = isObject(policy) ? policy : {}
  const f = (name) => `latest_scene_policy.${name}`
  return {
    facts: [
      item('max_cloud_fraction', 'methods.scene.max_cloud', p.max_cloud_fraction, { ...PERCENT, reason: 'invalid_value' }, f('max_cloud_fraction')),
      item('min_water_pixels', 'methods.scene.min_water', p.min_water_pixels, { ...COUNT, reason: 'invalid_value' }, f('min_water_pixels')),
      item('poll_interval_hours', 'methods.scene.poll', p.poll_interval_hours, HOURS, f('poll_interval_hours')),
      item('min_scan_interval_hours', 'methods.scene.min_interval', p.min_scan_interval_hours, HOURS, f('min_scan_interval_hours')),
      item('settle_hours', 'methods.scene.settle', p.settle_hours, HOURS, f('settle_hours')),
    ],
  }
}

// ---------------------------------------------------------- references

/** A DOI as a doi.org link (the DOI itself is shown as returned); null
 * without one. */
export function doiHref(doi) {
  const d = text(doi)
  return d ? `https://doi.org/${encodeURI(d.trim())}` : null
}

function referencesModel(refs) {
  return list(refs).filter(isObject).map((r, i) => ({
    id: text(r.id) ?? `ref_${i}`,
    citation: typeof r.citation === 'string' ? r.citation : null,
    doi: text(r.doi),
    href: doiHref(r.doi),
    note: serverText(r.note),
    source: sourceRef({ endpoint: METHODS_ENDPOINT, field: `references[${i}]`, value: r.id }),
  }))
}

// -------------------------------------------------------------- the page

/**
 * The Methods page model.
 * @param {{methods: object|null, request: {loading?, error?},
 *   levelB?: object}} input  `levelB` is a `buildLevelBModel` result.
 */
export function buildMethodsModel({ methods, request, levelB } = {}) {
  const req = isObject(request) ? request : {}
  if (!isObject(methods)) {
    if (req.error) return { state: 'error', error: { error: req.error, endpoint: METHODS_ENDPOINT }, sections: [], anchors: [] }
    return { state: 'loading', sections: [], anchors: [] }
  }
  const indices = list(methods.indices).map(indexCard)
  const sections = [
    { id: 'sources', titleKey: 'methods.section.sources', sentinel2: sentinel2Model(methods.sentinel2), modis: modisModel(methods.modis) },
    { id: 'indices', titleKey: 'methods.section.indices', cards: indices },
    { id: 'quality', titleKey: 'methods.section.quality', ...qualityModel(methods.sentinel2, methods.quality_screens) },
    { id: 'gates', titleKey: 'methods.section.gates', ...gatesModel(methods.gates) },
    { id: 'baseline', titleKey: 'methods.section.baseline', baseline: baselineModel(methods, levelB) },
    { id: 'latest_scene', titleKey: 'methods.section.latest_scene', ...latestSceneModel(methods.latest_scene_policy) },
    { id: 'references', titleKey: 'methods.section.references', references: referencesModel(methods.references) },
  ]
  const { baseline } = sections.find((s) => s.id === 'baseline')
  const anchors = [
    ...METHODS_SECTIONS,
    'sentinel2', 'modis', 'robust_z',
    ...indices.map((c) => c.anchor),
    ...(baseline.state === 'test' ? ['level_a', 'level_b'] : []),
  ]
  return {
    state: 'ready',
    apiVersion: text(methods.api_version),
    apiVersionSource: sourceRef({ endpoint: METHODS_ENDPOINT, field: 'api_version', value: methods.api_version }),
    isTest: baseline.state === 'test',
    disclaimer: text(methods.disclaimer) ? { text: methods.disclaimer, endpoint: METHODS_ENDPOINT } : null,
    sections,
    toc: sections.map((s) => ({ id: s.id, titleKey: s.titleKey })),
    anchors,
    rawUrl: sourceRef({ endpoint: METHODS_ENDPOINT }).url,
  }
}

/** Whether the Level B summary should be requested for this `/methods`
 * response: only with a valid TEST baseline. */
export function wantsLevelB(methods) {
  const b = isObject(methods) && isObject(methods.baseline) ? methods.baseline : null
  return Boolean(b && b.mode === 'test' && b.valid === true)
}
