/**
 * mapModel: everything the raster map page (`/map`) shows, as data -- i18n
 * messages with already-formatted params, formatted values, status-chip
 * descriptors and source refs -- so the page and its components are thin
 * renderers and every rule here runs under `node --test` (dashboard spec
 * §4.2, §4.6; test-baseline spec §6, §7).
 *
 * Data source (read-only; nothing computed that the API did not send):
 *   - `GET /raster-scan` (RasterScanResponse): run provenance, scene_dates,
 *     source_metadata.scene_ids, latest_scene, poll;
 *   - `GET /raster-scan/highlights?n=&run_id=` (RasterHighlightsResponse or
 *     RasterAnomalyHighlightsResponse): pins, counts, quality screens,
 *     baseline block -- the server picks the mode (no `mode` is sent);
 *   - `GET /raster-scan/pixel` (RasterPixelResponse incl. `anomaly`): the
 *     inspected cell;
 *   - the URL query (src/lib/permalink.js) for the permalink.
 *
 * Rules kept here:
 *   - no client-side science: no z-score, no threshold, no classification.
 *     The only arithmetic is formatting, sorting pins by the API's rank, the
 *     sum of the API's own count buckets (shown as a partition check, never
 *     used to correct anything) and bar widths from the API's shares;
 *   - an unknown is "—" with a reason, never 0; a real zero stays 0;
 *   - anomaly values are always labelled TEST (they exist only against the
 *     TEST cell baseline); no pin carries a risk tier and no code path here
 *     reads `risk_tier`;
 *   - a failed pins request is an error with its HTTP status and the
 *     server's reason (e.g. 409 `mode_off`), never "no pins".
 *
 * Limitations: pure functions of their inputs. They neither fetch nor
 * decide what a reading means.
 */
import { apiAssetUrl } from '../api/client.js'
import { formatValue, NULL_TEXT } from './format.js'
import { chipForAnomalyLevel, chipForPixelState } from './statusChip.js'
import { sourceRef, refForPixelField, refForRasterField, requestPath } from './provenance.js'
import { cellCsv, pinsCsv, toCsv } from './csv.js'
import { decodeView, encodeView } from './permalink.js'
import { latestSceneBlock, pollBlock } from './overviewModel.js'

/** Pins the user may ask for (`/raster-scan/highlights` `n` is 3-10). */
export const PIN_N_MIN = 3
export const PIN_N_MAX = 10
export const PIN_N_DEFAULT = 5
export const PIN_N_OPTIONS = Object.freeze([3, 4, 5, 6, 7, 8, 9, 10])

/** The four stored raster indices, their display names and /methods anchors
 * (MethodsIndex.raster_band -> key). Display names only. */
export const INDEX_FIELDS = Object.freeze([
  Object.freeze({ band: 'ndci', label: 'NDCI', methods: 'ndci' }),
  Object.freeze({ band: 'bda2', label: '2BDA', methods: '2bda' }),
  Object.freeze({ band: 'bda3', label: '3BDA', methods: '3bda' }),
  Object.freeze({ band: 'b2_b3', label: 'B2/B3', methods: 'b2_b3_ratio' }),
])

/** RasterAnomalyCounts' seven "not assessable" buckets, in the server's rule
 * order (each unassessable cell is counted once, in the first rule it fails). */
export const COUNT_REASON_KEYS = Object.freeze([
  'invalid', 'low_signal', 'too_old', 'not_after_history', 'no_baseline', 'insufficient_dates', 'zero_mad',
])

/** Visible bands as stored (raw DN): red B4, green B3, blue B2. */
export const VISIBLE_BANDS = Object.freeze(['red', 'green', 'blue'])

const PIN_ENDPOINT = '/raster-scan/highlights'
const INDEX_DECIMALS = 4

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)
const finite = (v) => typeof v === 'number' && Number.isFinite(v)
const hasValue = (v) => v !== null && v !== undefined
const msg = (key, params = {}) => ({ key, params })
const caveat = (key, params = {}) => ({ key, params, tone: 'attention' })
const text = (v) => (typeof v === 'string' && v.trim() !== '' ? v : null)

// Ids and API codes, verbatim ("—" when absent); never number-formatted.
const plain = (v) => ((finite(v) || (typeof v === 'string' && v !== '')) ? String(v) : NULL_TEXT)
const countText = (v) => formatValue(v, { kind: 'count' }).text
const dateText = (v) => formatValue(v, { kind: 'date' }).text

/** One displayed value: the API value, its spec and formatValue's result. */
function val(raw, spec) {
  const r = formatValue(raw, spec)
  return { raw: hasValue(raw) ? raw : null, spec, text: r.text, isNull: r.isNull, reason: r.reason }
}

const coordSpec = (reason) => ({ kind: 'coord', decimals: 5, unit: '°', ...(reason ? { reason } : {}) })

/** Pin count clamped to 3-10; anything unusable is the default 5. */
export function clampPinCount(n) {
  const v = typeof n === 'string' && /^\d+$/.test(n) ? Number(n) : n
  if (!Number.isInteger(v)) return PIN_N_DEFAULT
  return Math.min(PIN_N_MAX, Math.max(PIN_N_MIN, v))
}

/** The legend text key for a pin mode; null for a mode this UI does not know. */
export function pinLegendKey(mode) {
  if (mode === 'ndci') return 'map.pins.legend_ndci'
  if (mode === 'anomaly') return 'map.pins.legend_anomaly'
  return null
}

/** Marker shape per mode: the two pin kinds never share a shape, and neither
 * is the hollow circle of a monitoring site. */
export function pinShape(mode) {
  if (mode === 'ndci') return 'square'
  if (mode === 'anomaly') return 'diamond'
  return null
}

/** `{status, reason, message, noResponse}` of a failed request: the HTTP
 * status, the server's machine reason (`detail.reason`, e.g. 'mode_off') and
 * its message (a string `detail`, or `detail.message`), all verbatim. */
export function errorInfo(error, endpoint) {
  const response = isObject(error) && isObject(error.response) ? error.response : null
  const detail = response && isObject(response.data) ? response.data.detail : null
  const status = response && Number.isInteger(response.status) ? response.status : null
  let reason = null
  let message = null
  if (typeof detail === 'string') message = text(detail)
  else if (isObject(detail)) {
    reason = text(detail.reason)
    message = text(detail.message)
  }
  return { status, reason, message, noResponse: isObject(error) && !response, endpoint: endpoint ?? null }
}

function highlightsParams(highlights) {
  return {
    run_id: highlights.run_id, n: highlights.n_requested,
    min_separation_m: highlights.min_separation_m, mode: highlights.mode,
  }
}

function pinSource(highlights, rank, field, value, unit, formulaKey, observedDate) {
  return sourceRef({
    endpoint: PIN_ENDPOINT, params: highlightsParams(highlights), field: `pins[rank=${rank}].${field}`,
    value, unit, observedDate, runId: highlights.run_id, formulaKey,
  })
}

function countSource(highlights, field, value, unit = 'count') {
  return sourceRef({
    endpoint: PIN_ENDPOINT, params: highlightsParams(highlights), field, value, unit, runId: highlights.run_id,
  })
}

/** The pins of `highlights`, sorted by the API's rank, valid ones only. */
function pinsOf(highlights) {
  const list = isObject(highlights) && Array.isArray(highlights.pins) ? highlights.pins : []
  return list.filter((p) => isObject(p) && Number.isInteger(p.rank)).sort((a, b) => a.rank - b.rank)
}

// ------------------------------------------------------------ counts block

/**
 * How the measured cells of the run were assessed, in plain words
 * (test-baseline spec §6 "Not met / not assessable"). Rows are in a fixed
 * order, each with a plain-language label key `map.counts.<id>` and a source.
 * `partition` restates the API's own invariant -- assessable plus the seven
 * reason buckets equals measured -- as a sum of the API's counts; a mismatch
 * is shown, never corrected.
 */
export function buildCountsBlock(highlights) {
  if (!isObject(highlights)) return null
  const mode = highlights.mode
  const quality = [
    {
      id: 'excluded_degenerate', labelKey: 'map.counts.excluded_degenerate',
      value: val(highlights.excluded_degenerate, { kind: 'count' }),
      source: countSource(highlights, 'excluded_degenerate', highlights.excluded_degenerate),
    },
    {
      id: 'excluded_low_signal', labelKey: 'map.counts.excluded_low_signal',
      // Null, not 0, when the screen could not run (no visible bands stored).
      value: val(highlights.excluded_low_signal, { kind: 'count' }),
      nullKey: 'map.counts.excluded_low_signal_null',
      source: countSource(highlights, 'excluded_low_signal', highlights.excluded_low_signal),
    },
  ]
  const qualityNote = text(highlights.quality_note)

  if (mode !== 'anomaly' || !isObject(highlights.counts)) {
    return {
      mode: mode === 'ndci' ? 'ndci' : null,
      headingKey: 'map.counts.heading_ndci',
      introKey: 'map.counts.intro_ndci',
      rows: [{
        id: 'cohort', labelKey: 'map.counts.cohort', group: 'total',
        value: val(highlights.cohort_size, { kind: 'count' }),
        source: countSource(highlights, 'cohort_size', highlights.cohort_size),
      }],
      partition: null,
      quality,
      qualityNote,
    }
  }

  const c = highlights.counts
  const row = (id, group, spec = { kind: 'count' }) => ({
    id, group, labelKey: `map.counts.${id}`, value: val(c[id], spec),
    source: countSource(highlights, `counts.${id}`, c[id], spec.kind === 'percent' ? 'fraction' : 'count'),
  })
  const rows = [
    row('measured', 'total'),
    row('assessable', 'assessable'),
    ...COUNT_REASON_KEYS.map((id) => row(id, 'reason')),
    row('watch', 'condition'),
    row('high', 'condition'),
    { ...row('flagged_share', 'share', { kind: 'percent', decimals: 2, reason: 'none_assessable' }), nullKey: 'map.counts.flagged_share_null' },
  ]

  const parts = [c.assessable, ...COUNT_REASON_KEYS.map((k) => c[k])]
  let partition
  if (parts.every(finite) && finite(c.measured)) {
    const sum = parts.reduce((a, b) => a + b, 0)
    const ok = sum === c.measured
    partition = {
      ok,
      sum,
      measured: c.measured,
      message: ok
        ? msg('map.counts.partition_ok', { sum: countText(sum), measured: countText(c.measured) })
        : caveat('map.counts.partition_mismatch', {
          sum: countText(sum), measured: countText(c.measured), diff: countText(Math.abs(sum - c.measured)),
        }),
    }
  } else {
    partition = { ok: null, sum: null, measured: finite(c.measured) ? c.measured : null, message: caveat('map.counts.partition_unknown') }
  }
  return {
    mode: 'anomaly', headingKey: 'map.counts.heading_anomaly', introKey: 'map.counts.intro_anomaly',
    rows, partition, quality, qualityNote,
  }
}

// --------------------------------------------------------------- pins list

/**
 * The pins block for the rail and the map layer.
 * @param {{highlights?, request?: {loading?, error?}, runId?, n?, show?}} input
 * @returns {{state, mode, isTest, shape, legendKey, headingKey, items, notes,
 *   serverReason, error, endpoint, counts, show, csv}}
 * States: 'no_raster' | 'loading' | 'error' | 'other_run' | 'unknown_mode' |
 * 'empty' | 'ready'.
 */
export function buildPinsModel(input) {
  const { highlights, request, runId, n, show = true } = isObject(input) ? input : {}
  const count = clampPinCount(n)
  const run = Number.isInteger(runId) ? runId : null
  const endpoint = requestPath(PIN_ENDPOINT, { n: count, run_id: run })
  const base = {
    state: 'loading', mode: null, isTest: false, shape: null, legendKey: null, headingKey: 'map.pins.heading',
    items: [], notes: [], serverReason: null, error: null, endpoint, counts: null, show: show !== false,
    n: count, csv: null,
  }
  if (run === null) return { ...base, state: 'no_raster', notes: [msg('map.pins.no_raster')] }
  const req = isObject(request) ? request : {}
  if (hasValue(req.error)) return { ...base, state: 'error', error: errorInfo(req.error, endpoint) }
  if (!isObject(highlights) || req.loading === true) return { ...base, state: 'loading' }
  if (highlights.run_id !== run) {
    return { ...base, state: 'other_run', notes: [caveat('map.pins.other_run', { pins_run: plain(highlights.run_id), run: plain(run) })] }
  }
  const mode = highlights.mode
  if (mode !== 'ndci' && mode !== 'anomaly') {
    return { ...base, state: 'unknown_mode', notes: [caveat('map.pins.unknown_mode', { mode: plain(mode) })] }
  }
  const isTest = mode === 'anomaly' // anomaly pins exist only against a TEST baseline
  const items = pinsOf(highlights).map((p) => {
    const ndci = isObject(p.index_values) ? p.index_values.ndci : null
    const ndciVal = val(ndci, { kind: 'index' })
    const z = isTest ? val(p.robust_z, { kind: 'z' }) : null
    return {
      rank: p.rank,
      lat: finite(p.pixel_centre_lat) ? p.pixel_centre_lat : null,
      lng: finite(p.pixel_centre_lng) ? p.pixel_centre_lng : null,
      onMap: finite(p.pixel_centre_lat) && finite(p.pixel_centre_lng),
      ndci: ndciVal,
      z,
      chip: isTest ? chipForAnomalyLevel(p.anomaly_level, true) : null,
      date: val(p.acquired_date, { kind: 'date' }),
      edge: p.edge_of_no_data === true,
      label: isTest
        ? msg('map.pins.row_label_anomaly', { rank: String(p.rank), z: z.text, ndci: ndciVal.text })
        : msg('map.pins.row_label_ndci', { rank: String(p.rank), ndci: ndciVal.text }),
    }
  })
  const notes = []
  if (items.length > 0 && items.length < count) {
    notes.push(msg('map.pins.fewer', { count: countText(items.length), n: countText(count) }))
  }
  if (items.some((p) => !p.onMap)) notes.push(caveat('map.pins.no_position'))
  if (show === false && items.length > 0) notes.push(msg('map.pins.hidden'))
  return {
    ...base,
    state: items.length === 0 ? 'empty' : 'ready',
    mode,
    isTest,
    shape: pinShape(mode),
    legendKey: pinLegendKey(mode),
    headingKey: isTest ? 'map.pins.heading_anomaly' : 'map.pins.heading_ndci',
    items,
    notes,
    serverReason: text(highlights.reason),
    counts: buildCountsBlock(highlights),
    csv: items.length > 0
      ? { filename: `highlight-pins-run-${plain(run)}.csv`, content: () => pinsCsv(highlights, { bom: true }) }
      : null,
  }
}

// ---------------------------------------------------------- pin inspector

function bandRows(bands, makeSource) {
  if (!isObject(bands)) return null
  return VISIBLE_BANDS.map((band) => ({
    id: band,
    labelKey: `map.bands.${band}`,
    value: val(bands[band], { kind: 'count' }),
    source: makeSource ? makeSource(band, bands[band]) : null,
  }))
}

/**
 * The popup/inspector view of one pin (dashboard spec §4.6, test-baseline
 * spec §6). Null when the response holds no pin of that rank.
 */
export function buildPinView(highlights, rank) {
  if (!isObject(highlights)) return null
  const pins = pinsOf(highlights)
  const pin = pins.find((p) => p.rank === rank)
  if (!pin) return null
  const mode = highlights.mode === 'anomaly' ? 'anomaly' : highlights.mode === 'ndci' ? 'ndci' : null
  const isTest = mode === 'anomaly'
  const iv = isObject(pin.index_values) ? pin.index_values : {}
  const observed = pin.acquired_date
  const src = (field, value, unit, formula) => pinSource(highlights, pin.rank, field, value, unit, formula, observed)

  const indices = INDEX_FIELDS.map((f) => {
    const raw = iv[f.band]
    const unreadable = Object.hasOwn(iv, f.band) && !finite(raw)
    return {
      id: f.band, label: f.label, href: `/methods#${f.methods}`, unreadable,
      value: val(raw, { kind: 'index', decimals: INDEX_DECIMALS, reason: unreadable ? 'unreadable_band' : 'not_available' }),
      source: src(`index_values.${f.band}`, raw, 'dimensionless', f.methods),
    }
  })

  const percentile = val(pin.percentile, { decimals: 3 })
  const counts = isObject(highlights.counts) ? highlights.counts : {}
  const baseline = isObject(highlights.baseline) ? highlights.baseline : {}
  const levelB = isObject(baseline.level_b) ? baseline.level_b : {}

  let anomaly = null
  if (isTest) {
    const row = (id, field, spec, unit) => ({
      id, labelKey: `map.anomaly.${id}`, value: val(pin[field], spec), source: src(field, pin[field], unit, 'robust_z'),
    })
    anomaly = {
      rows: [
        row('robust_z', 'robust_z', { kind: 'z' }, 'dimensionless'),
        row('median_ndci', 'median_ndci', { kind: 'index', decimals: INDEX_DECIMALS }, 'dimensionless'),
        row('mad', 'mad', { kind: 'index', decimals: INDEX_DECIMALS }, 'dimensionless'),
        row('n_dates', 'n_dates', { kind: 'count' }, 'count'),
      ],
      chip: chipForAnomalyLevel(pin.anomaly_level, true),
      baselineVersion: plain(baseline.version),
      seasonKey: plain(levelB.season_key),
    }
  }

  const params = highlightsParams(highlights)
  return {
    rank: pin.rank,
    count: pins.length,
    mode,
    isTest,
    shape: pinShape(mode),
    headingKey: isTest ? 'map.pins.heading_anomaly' : 'map.pins.heading_ndci',
    legendKey: pinLegendKey(mode),
    title: msg('map.pin.title', { rank: String(pin.rank), count: countText(pins.length) }),
    indices,
    percentile: {
      value: percentile,
      note: isTest
        ? msg('map.pin.percentile_anomaly', { assessable: countText(counts.assessable) })
        : msg('map.pin.percentile_ndci', { cohort: countText(highlights.cohort_size) }),
      source: src('percentile', pin.percentile, null, null),
    },
    acquiredDate: { value: val(pin.acquired_date, { kind: 'date' }), source: src('acquired_date', pin.acquired_date, null, null) },
    acquiredAt: { value: val(pin.acquired_at, { kind: 'datetime-utc' }), source: src('acquired_at', pin.acquired_at, null, null) },
    cell: {
      lat: val(pin.cell_lat, coordSpec()), lng: val(pin.cell_lng, coordSpec()),
      source: src('cell_lat', pin.cell_lat, '°', null),
    },
    centre: {
      lat: val(pin.pixel_centre_lat, coordSpec()), lng: val(pin.pixel_centre_lng, coordSpec()),
      source: src('pixel_centre_lat', pin.pixel_centre_lat, '°', null),
    },
    runId: plain(highlights.run_id),
    ranking: text(highlights.ranking),
    separation: msg('map.pin.separation', { m: countText(highlights.min_separation_m) }),
    edge: pin.edge_of_no_data === true
      ? caveat('map.pin.edge_true')
      : pin.edge_of_no_data === false ? msg('map.pin.edge_false') : msg('map.pin.edge_unknown'),
    bands: bandRows(pin.visible_bands_dn, (band, v) => src(`visible_bands_dn.${band}`, v, 'DN', null)),
    anomaly,
    caveatKey: 'map.pin.caveat',
    counts: buildCountsBlock(highlights),
    disclaimer: text(highlights.disclaimer),
    target: finite(pin.pixel_centre_lat) && finite(pin.pixel_centre_lng)
      ? { lat: pin.pixel_centre_lat, lng: pin.pixel_centre_lng } : null,
    cellQuery: finite(pin.cell_lat) && finite(pin.cell_lng) ? { lat: pin.cell_lat, lng: pin.cell_lng } : null,
    csv: {
      filename: `pin-${pin.rank}-run-${plain(highlights.run_id)}.csv`,
      content: () => pinsCsv({ ...highlights, pins: [pin] }, { bom: true }),
    },
    rawUrl: apiAssetUrl(requestPath(PIN_ENDPOINT, params)),
  }
}

// --------------------------------------------------------- cell inspector

/** 'reading' | 'not_measured' | 'outside'. Anything not positively a reading
 * (including a state this build does not know) is drawn as not measured. */
export function cellState(pixel) {
  if (!isObject(pixel)) return null
  if (pixel.state === 'outside_study_area') return 'outside'
  return pixel.state === 'reading' ? 'reading' : 'not_measured'
}

/**
 * The cell inspector view of one `/raster-scan/pixel` response. Index values,
 * dates and coordinates only for a reading; the anomaly block only when the
 * response carries `anomaly` (TEST cell baseline).
 */
export function buildCellModel(pixel) {
  if (!isObject(pixel)) return null
  const state = cellState(pixel)
  const runId = plain(pixel.run_id)
  const rowColumn = Number.isInteger(pixel.pixel_row) && Number.isInteger(pixel.pixel_col)
    ? `-r${pixel.pixel_row}-c${pixel.pixel_col}` : ''
  const model = {
    state,
    chip: chipForPixelState(pixel.state),
    meaning: text(pixel.meaning),
    runId,
    runSource: refForPixelField(pixel, 'run_id'),
    disclaimer: text(pixel.disclaimer),
    indices: null,
    acquiredDate: null,
    acquiredAt: null,
    cell: null,
    centre: null,
    scale: null,
    anomaly: null,
    csv: { filename: `cell-run-${runId}${rowColumn}.csv`, content: () => cellCsv(pixel, { bom: true }) },
    rawUrl: refForPixelField(pixel, 'state').url,
  }
  if (state !== 'reading') return model

  const iv = isObject(pixel.index_values) ? pixel.index_values : {}
  const unreadableList = Array.isArray(pixel.unreadable_bands) ? pixel.unreadable_bands : []
  model.indices = INDEX_FIELDS.map((f) => {
    const raw = iv[f.band]
    const unreadable = unreadableList.includes(f.band) || (Object.hasOwn(iv, f.band) && !finite(raw))
    return {
      id: f.band, label: f.label, href: `/methods#${f.methods}`, unreadable,
      value: val(raw, { kind: 'index', decimals: INDEX_DECIMALS, reason: unreadable ? 'unreadable_band' : 'not_available' }),
      source: refForPixelField(pixel, `index_values.${f.band}`),
    }
  })
  model.acquiredDate = { value: val(pixel.acquired_date, { kind: 'date' }), source: refForPixelField(pixel, 'acquired_date') }
  model.acquiredAt = { value: val(pixel.acquired_at, { kind: 'datetime-utc' }), source: refForPixelField(pixel, 'acquired_at') }
  model.cell = {
    lat: val(pixel.cell_lat, coordSpec()), lng: val(pixel.cell_lng, coordSpec()),
    source: refForPixelField(pixel, 'cell_lat'),
  }
  model.centre = {
    lat: val(pixel.pixel_centre_lat, coordSpec()), lng: val(pixel.pixel_centre_lng, coordSpec()),
    source: refForPixelField(pixel, 'pixel_centre_lat'),
  }
  model.scale = {
    value: val(pixel.scale_m, { kind: 'count', unit: 'm' }),
    note: finite(pixel.scale_m) ? msg('map.cell.sampling', { scale: countText(pixel.scale_m) }) : msg('map.cell.sampling_unknown'),
    source: refForPixelField(pixel, 'scale_m'),
  }

  const a = isObject(pixel.anomaly) ? pixel.anomaly : null
  if (a) {
    // Why z is "—": the server's first failing rule, or simply absent.
    const reason = text(a.reason)
    const row = (id, field, spec, unit) => ({
      id, labelKey: `map.anomaly.${id}`, value: val(a[field], { ...spec, reason: reason ?? 'not_available' }),
      source: refForPixelField(pixel, `anomaly.${field}`),
      unit,
    })
    model.anomaly = {
      rows: [
        row('robust_z', 'robust_z', { kind: 'z' }),
        row('median_ndci', 'median_ndci', { kind: 'index', decimals: INDEX_DECIMALS }),
        row('mad', 'mad', { kind: 'index', decimals: INDEX_DECIMALS }),
        row('n_dates', 'n_dates', { kind: 'count' }),
      ],
      chip: chipForAnomalyLevel(a.level, true),
      reason,
      seasonKey: plain(a.season_key),
      baselineVersion: plain(a.baseline_version),
      bands: bandRows(a.visible_bands_dn, (band) => refForPixelField(pixel, `anomaly.visible_bands_dn.${band}`)),
    }
  }
  return model
}

// ------------------------------------------------------------------ rail

/** Run provenance rows of the served raster (dashboard spec §4.2). */
export function buildRunModel(raster) {
  if (!isObject(raster) || !hasValue(raster.run_id)) {
    return { state: 'empty', rows: [], sceneIds: [], sceneIdsSource: null, staleNote: null, serverReason: isObject(raster) ? text(raster.reason) : null }
  }
  const row = (id, spec, field = id) => ({
    id, labelKey: `map.run.${id}`, value: spec ? val(raster[field], spec) : null, code: spec ? null : plain(raster[field]),
    source: refForRasterField(raster, field),
  })
  const meta = isObject(raster.source_metadata) ? raster.source_metadata : {}
  const sceneIds = Array.isArray(meta.scene_ids) ? meta.scene_ids.filter((s) => typeof s === 'string' && s !== '') : []
  return {
    state: hasValue(raster.stale_run_id) ? 'stale' : 'ready',
    rows: [
      row('run_id', null),
      row('status', null),
      row('date_used', { kind: 'date' }),
      row('scale_m', { kind: 'count', unit: 'm' }),
      row('completed_at', { kind: 'datetime-utc' }),
      row('cell_count', { kind: 'count' }),
      row('scene_count', { kind: 'count' }),
    ],
    sceneIds,
    sceneIdsSource: refForRasterField(raster, 'source_metadata.scene_ids'),
    staleNote: hasValue(raster.stale_run_id)
      ? caveat('overview.stale.raster', { run: plain(raster.run_id), stale_run: plain(raster.stale_run_id) })
      : null,
    serverReason: null,
  }
}

const SCENE_CHART_COLUMNS = Object.freeze(['date', 'cells', 'share', 'run_id', 'endpoint'])

/** Bars for `scene_dates[].share` with their text alternative rows; the
 * API's order and shares, never recomputed from the cell counts. */
export function buildSceneChart(raster) {
  const days = isObject(raster) && Array.isArray(raster.scene_dates) ? raster.scene_dates.filter(isObject) : null
  const run = isObject(raster) ? plain(raster.run_id) : NULL_TEXT
  if (!days || days.length === 0) {
    return { state: 'empty', rows: [], empty: caveat('map.chart.none'), caption: null, alt: null, source: isObject(raster) ? refForRasterField(raster, 'scene_dates') : null, csv: null }
  }
  const rows = days.map((d, i) => ({
    key: `${i}-${d.date}`,
    date: dateText(d.date),
    share: val(d.share, { kind: 'percent', decimals: 1 }),
    cells: val(d.cells, { kind: 'count' }),
    // Layout only: the bar's width is the API's share.
    width: finite(d.share) ? Math.max(0, Math.min(100, d.share * 100)) : 0,
  }))
  return {
    state: 'ready',
    rows,
    empty: null,
    caption: msg('map.chart.caption', { run, days: countText(rows.length) }),
    alt: msg('map.chart.alt', { list: rows.map((r) => `${r.date} ${r.share.text}`).join('; ') }),
    source: refForRasterField(raster, 'scene_dates'),
    csv: {
      filename: `scene-dates-run-${run}.csv`,
      content: () => toCsv(SCENE_CHART_COLUMNS, days.map((d) => ({
        date: d.date, cells: d.cells, share: d.share, run_id: raster.run_id, endpoint: 'GET /raster-scan',
      })), { bom: true }),
    },
  }
}

/**
 * Everything the rail shows besides the pins: run provenance, the
 * scene-date chart and the latest-scene and poll lines exactly as on the
 * Overview (src/lib/overviewModel.js).
 */
export function buildRailModel({ raster, request, methods, now } = {}) {
  const req = isObject(request) ? { loading: request.loading === true, error: request.error ?? null } : { loading: false, error: null }
  const r = isObject(raster) ? raster : null
  const nowMs = now instanceof Date ? now.getTime() : finite(now) ? now : Date.now()
  return {
    run: buildRunModel(r),
    chart: buildSceneChart(r),
    latestScene: latestSceneBlock(r, req, isObject(methods) ? methods : null),
    poll: pollBlock(r, req, nowMs),
  }
}

// ------------------------------------------------------------- permalink

/** The view named by a URL query (validated by permalink.decodeView). */
export function readPermalink(search) {
  return decodeView(search)
}

/**
 * Apply a decoded permalink to the raster now served.
 *   - lat/lng select that cell and fly to it (zoom from the link, if any);
 *   - `pin` selects that pin of the run -- only when the link's run is the
 *     one served (pins belong to one run);
 *   - a link to a run that is no longer served says so and loads the latest;
 *   - a layer this run cannot show (True Color without stored RGB) falls
 *     back to NDCI, with a note.
 * @returns {{selection, layer, zoom, fly, notes, runGone}}
 */
export function applyPermalink(view, { raster } = {}) {
  const v = isObject(view) ? view : {}
  // Before the raster has loaded nothing is known about the run, so nothing
  // is claimed about it yet (the page applies the link again once it has).
  const known = isObject(raster)
  const runId = known && Number.isInteger(raster.run_id) ? raster.run_id : null
  const linked = Number.isInteger(v.runId) ? v.runId : null
  const runGone = known && linked !== null && linked !== runId
  const notes = []
  if (runGone) {
    notes.push(runId === null
      ? caveat('map.permalink.run_gone_none', { run: String(linked) })
      : caveat('map.permalink.run_gone', { run: String(linked), latest: String(runId) }))
  }
  let selection = null
  if (finite(v.lat) && finite(v.lng)) selection = { kind: 'cell', lat: v.lat, lng: v.lng }
  else if (Number.isInteger(v.pin)) {
    if (runGone) notes.push(caveat('map.permalink.pin_gone', { pin: String(v.pin) }))
    else if (runId !== null || !known) selection = { kind: 'pin', rank: v.pin }
  }
  let layer = typeof v.layer === 'string' ? v.layer : 'ndci'
  if (layer === 'true_color' && known && !text(raster.true_color_url)) {
    layer = 'ndci'
    notes.push(msg('map.permalink.layer_unavailable'))
  }
  const zoom = finite(v.zoom) ? v.zoom : null
  return {
    selection,
    layer,
    zoom,
    fly: selection?.kind === 'cell' ? { lat: selection.lat, lng: selection.lng, zoom } : null,
    notes,
    runGone,
  }
}

/** The current view as a query string (no "?"): the selected cell's lat/lng
 * or the selected pin, the served run, the layer, the zoom and optionally
 * the language. Nothing else is written. */
export function serializeView({ selection, layer, zoom, runId, lang } = {}) {
  const s = isObject(selection) ? selection : null
  return encodeView({
    lat: s?.kind === 'cell' ? s.lat : undefined,
    lng: s?.kind === 'cell' ? s.lng : undefined,
    pin: s?.kind === 'pin' ? s.rank : undefined,
    runId,
    layer,
    zoom,
    lang,
  })
}
