/**
 * sitesModel: everything the Monitoring-sites pages (`/sites`,
 * `/sites/:siteId`) show, as data -- formatted values, status-chip
 * descriptors, i18n keys, source refs, sort keys and export builders -- so
 * the pages are thin renderers and every rule here runs under `node --test`
 * (dashboard spec §4.3, §5, §10; test-baseline spec §5).
 *
 * Data source (read-only; nothing computed that the API did not send):
 *   - `GET /risk-map` (RiskMapResponse, backend/src/schemas.py): the seven
 *     fixed sites' latest scheduler-cached Sentinel-2 readings
 *     (RiskMapProperties) and the response's `baseline` block (BaselineInfo,
 *     present only with BASELINE_MODE=test), which is the authority for the
 *     site anomaly fields it travels with;
 *   - `GET /timeseries?lat=&lng=` (TimeseriesResponse): the MODIS-Aqua
 *     `chlor_a` series (mg m⁻³) with its day-of-year-climatology
 *     `anomaly_z` -- a separate sensor and quantity, never merged with the
 *     Sentinel-2 indices;
 *   - `GET /methods` `modis` (MethodsModis.grid_resolution_m, via
 *     useBaseline().methods): the Level-3 grid the MODIS product is sampled
 *     on (4638 m), never a hard-coded "1 km".
 *
 * Rules kept here:
 *   - unknown is "—" with a reason (the site's own status, the server's
 *     `error` text verbatim, `signal_anomaly_reason`, a point's `reason`);
 *     never 0, and a real 0 stays 0;
 *   - sorting is stable and puts unknown values last in both directions;
 *   - an anomaly chip appears only when the response's baseline is a valid
 *     TEST baseline AND `signal_anomaly_level` is non-null; it always
 *     carries "(TEST)". The anomaly column exists only while the response
 *     has a baseline block (mode test, valid or not);
 *   - no risk tier is ever shown (`risk_level` is null while risk
 *     evaluation is inactive; the status chip says so);
 *   - the GeoJSON export is the `/risk-map` response verbatim; the CSV is
 *     src/lib/csv.js `sitesCsv` / `timeseriesCsv` (documented columns).
 *
 * Limitations: pure functions of their inputs; no fetching. They never
 * decide what a reading means.
 */
import { apiAssetUrl } from '../api/client.js'
import { formatValue, formatDateSpan, toUtcMs, NULL_TEXT } from './format.js'
import { chipForSite, chipForAnomalyLevel, SITE_STATUSES } from './statusChip.js'
import { refForSiteField, sourceRef, requestPath, WORD_UNITS } from './provenance.js'
import { sitesCsv, timeseriesCsv } from './csv.js'

/** `/timeseries` reads a multi-year MODIS archive and can be slow; the
 * shared client's 30 s default is too short for a cold request. */
export const TIMESERIES_TIMEOUT_MS = 120000

/** The four site indices (`index_values` keys = MethodsIndex.key, so they
 * are also the /methods anchors). Labels are scientific symbols, never
 * translated. */
export const SITE_INDEX_FIELDS = Object.freeze([
  Object.freeze({ key: 'ndci', label: 'NDCI' }),
  Object.freeze({ key: '2bda', label: '2BDA' }),
  Object.freeze({ key: '3bda', label: '3BDA' }),
  Object.freeze({ key: 'b2_b3_ratio', label: 'B2/B3' }),
])

const INDEX_DECIMALS = 4
const MG_M3 = 'mg m⁻³'

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)
const finite = (v) => typeof v === 'number' && Number.isFinite(v)
const hasValue = (v) => v !== null && v !== undefined
const text = (v) => (typeof v === 'string' && v.trim() !== '' ? v : null)
const msg = (key, params = {}) => ({ key, params })
const plain = (v) => ((finite(v) || (typeof v === 'string' && v !== '')) ? String(v) : NULL_TEXT)

/** One displayed value: the API value, its spec and formatValue's result. */
function val(raw, spec) {
  const r = formatValue(raw, spec)
  return { raw: hasValue(raw) ? raw : null, spec, text: r.text, isNull: r.isNull, reason: r.reason }
}

// ---------------------------------------------------------------- columns

/**
 * The `/sites` table columns, in display order. `path` is the API field
 * the column shows (named in its header popover), `sort` the comparison
 * kind, `aboutKey` the i18n definition. Index columns carry a scientific
 * `label` instead of a `labelKey`. `anomaly` is shown only while the
 * response has a baseline block.
 */
export const SITE_COLUMNS = Object.freeze([
  { id: 'name', labelKey: 'sites.col.name', path: 'features[].properties.name', sort: 'text' },
  { id: 'lat', labelKey: 'sites.col.lat', path: 'features[].geometry.coordinates[1]', sort: 'number', unit: '°', num: true },
  { id: 'lng', labelKey: 'sites.col.lng', path: 'features[].geometry.coordinates[0]', sort: 'number', unit: '°', num: true },
  { id: 'status', labelKey: 'sites.col.status', path: 'features[].properties.status', sort: 'number' },
  { id: 'actual_date', labelKey: 'sites.col.actual_date', path: 'features[].properties.actual_date', sort: 'number', num: true },
  { id: 'cloud_fraction', labelKey: 'sites.col.cloud_fraction', path: 'features[].properties.cloud_fraction', sort: 'number', unit: 'fraction', num: true },
  ...SITE_INDEX_FIELDS.map((f) => ({
    id: f.key, label: f.label, path: `features[].properties.index_values.${f.key}`, sort: 'number', unit: 'dimensionless', formula: f.key, num: true,
  })),
  { id: 'index_used', labelKey: 'sites.col.index_used', path: 'features[].properties.index_used', sort: 'text' },
  { id: 'fetched_at', labelKey: 'sites.col.fetched_at', path: 'features[].properties.fetched_at', sort: 'number', num: true },
  { id: 'stale', labelKey: 'sites.col.stale', path: 'features[].properties.stale', sort: 'number' },
  { id: 'anomaly', labelKey: 'sites.col.anomaly', path: 'features[].properties.signal_anomaly_level', sort: 'number', formula: 'robust_z', testOnly: true },
].map((c) => Object.freeze({ unit: null, formula: null, num: false, testOnly: false, ...c, aboutKey: `sites.about.${c.id}` })))

export const SORT_DIRECTIONS = Object.freeze(['asc', 'desc'])
/** No sort: the rows keep the API's order (the server's site-grid order). */
export const DEFAULT_SORT = null

function sourceRow(id, labelKey, rowText, extra = {}) {
  return { id, labelKey, text: rowText, textKey: null, href: null, ...extra }
}

/** The header popover of one column: endpoint, field path, unit, what the
 * column means, and the formula link for an index. Same row shape as a
 * `sourceRef`, so SourceChip renders it. */
export function columnSource(column) {
  const c = isObject(column) ? column : {}
  const unit = typeof c.unit === 'string' ? c.unit : null
  return {
    endpoint: '/risk-map',
    field: typeof c.path === 'string' ? c.path : null,
    url: apiAssetUrl('/risk-map'),
    rows: [
      sourceRow('endpoint', 'source.endpoint', `GET ${requestPath('/risk-map')}`),
      sourceRow('field', 'source.field', typeof c.path === 'string' ? c.path : NULL_TEXT),
      sourceRow('unit', 'source.unit', unit ?? NULL_TEXT, { textKey: unit && WORD_UNITS.includes(unit) ? `unit.${unit}` : null }),
      sourceRow('about', 'sites.source.about', NULL_TEXT, { textKey: typeof c.aboutKey === 'string' ? c.aboutKey : null }),
      sourceRow('formula', 'source.formula', c.formula ?? NULL_TEXT, { href: c.formula ? `/methods#${c.formula}` : null }),
    ],
  }
}

// --------------------------------------------------------------- baseline

/**
 * The baseline block a `/risk-map` response carries (BaselineInfo), read
 * for display: `present` (mode test, valid or not), `isTest` (a valid TEST
 * baseline -- the only case an anomaly chip may show), version and reason.
 */
export function siteBaseline(riskMap) {
  const block = isObject(riskMap) && isObject(riskMap.baseline) ? riskMap.baseline : null
  const present = block !== null && block.mode === 'test'
  return {
    present,
    isTest: present && block.valid === true,
    version: present ? text(block.version) : null,
    reason: present ? text(block.reason) : null,
    block: present ? block : null,
  }
}

/** Why a site's values are "—": its own status code (reason.<status>), and
 * the server's `error` text verbatim when the status is 'error'. */
function siteNullReason(props) {
  if (props.status === 'ok') return { code: 'not_available', text: null }
  const code = typeof props.status === 'string' && props.status !== '' ? props.status : 'no_usable_data'
  return { code, text: props.status === 'error' ? text(props.error) : null }
}

/**
 * The anomaly cell of one site. `chip` only for a valid TEST baseline and a
 * non-null `signal_anomaly_level` (always the "(TEST)" variant); otherwise
 * z is "—" with `signal_anomaly_reason` (or the baseline's own reason).
 */
export function anomalyCell(feature, baseline) {
  const f = isObject(feature) ? feature : {}
  const props = isObject(f.properties) ? f.properties : {}
  const b = isObject(baseline) ? baseline : siteBaseline(null)
  const level = typeof props.signal_anomaly_level === 'string' && props.signal_anomaly_level !== '' ? props.signal_anomaly_level : null
  const shown = b.isTest === true && level !== null
  const reasonCode = shown ? null : (text(props.signal_anomaly_reason) ?? (b.present && !b.isTest && b.reason ? `baseline_invalid:${b.reason}` : 'not_available'))
  return {
    visible: b.present === true,
    shown,
    chip: shown ? chipForAnomalyLevel(level, true) : null,
    z: shown
      ? val(props.signal_robust_z, { kind: 'z' })
      : val(null, { kind: 'z', reason: reasonCode }),
    reasonCode,
    zSource: refForSiteField(f, 'signal_robust_z'),
    levelSource: refForSiteField(f, 'signal_anomaly_level'),
  }
}

// ------------------------------------------------------------------- rows

const STATUS_ORDER = Object.freeze(Object.fromEntries(SITE_STATUSES.map((s, i) => [s, i])))

/** One `/sites` table row (also the card on narrow screens). */
export function buildSiteRow(feature, baseline) {
  const f = isObject(feature) ? feature : {}
  const props = isObject(f.properties) ? f.properties : {}
  const coords = isObject(f.geometry) && Array.isArray(f.geometry.coordinates) ? f.geometry.coordinates : []
  const id = plain(props.site_id)
  const why = siteNullReason(props)
  const iv = isObject(props.index_values) ? props.index_values : null
  const indexReason = iv ? 'not_available' : why.code
  const anomaly = anomalyCell(f, baseline)
  const cells = {
    lat: val(coords[1], { unit: '°' }),
    lng: val(coords[0], { unit: '°' }),
    actual_date: val(props.actual_date, { kind: 'date', reason: why.code }),
    cloud_fraction: val(props.cloud_fraction, { kind: 'percent', reason: why.code }),
    fetched_at: val(props.fetched_at, { kind: 'datetime-utc', reason: props.status === 'no_data_yet' ? 'no_data_yet' : 'not_available' }),
  }
  for (const fld of SITE_INDEX_FIELDS) {
    cells[fld.key] = val(iv ? iv[fld.key] : null, { kind: 'index', decimals: INDEX_DECIMALS, reason: indexReason })
  }
  const sources = {
    name: refForSiteField(f, 'name'),
    lat: refForSiteField(f, 'lat'),
    lng: refForSiteField(f, 'lng'),
    status: refForSiteField(f, 'status'),
    actual_date: refForSiteField(f, 'actual_date'),
    cloud_fraction: refForSiteField(f, 'cloud_fraction'),
    index_used: refForSiteField(f, 'index_used'),
    fetched_at: refForSiteField(f, 'fetched_at'),
    stale: refForSiteField(f, 'stale'),
  }
  for (const fld of SITE_INDEX_FIELDS) sources[fld.key] = refForSiteField(f, `index_values.${fld.key}`)

  const sortNumber = (v) => (finite(v) ? v : null)
  const sort = {
    name: text(props.name)?.toLowerCase() ?? null,
    lat: sortNumber(coords[1]),
    lng: sortNumber(coords[0]),
    status: typeof props.status === 'string' && Object.hasOwn(STATUS_ORDER, props.status) ? STATUS_ORDER[props.status] : SITE_STATUSES.length,
    actual_date: toUtcMs(props.actual_date),
    cloud_fraction: sortNumber(props.cloud_fraction),
    index_used: text(props.index_used)?.toLowerCase() ?? null,
    fetched_at: toUtcMs(props.fetched_at),
    stale: typeof props.stale === 'boolean' ? (props.stale ? 1 : 0) : null,
    anomaly: anomaly.shown ? sortNumber(props.signal_robust_z) : null,
  }
  for (const fld of SITE_INDEX_FIELDS) sort[fld.key] = sortNumber(iv ? iv[fld.key] : null)

  return {
    id,
    name: text(props.name) ?? id,
    href: `/sites/${encodeURIComponent(id)}`,
    status: typeof props.status === 'string' ? props.status : null,
    chips: chipForSite(f),
    nullReason: why.code,
    nullReasonText: why.text,
    indexUsed: text(props.index_used),
    stale: props.stale === true,
    cells,
    sources,
    anomaly,
    sort,
  }
}

/**
 * Rows sorted by one column, stably (equal keys keep the API's order) and
 * with unknown values last whichever the direction. Returns a new array.
 */
export function sortRows(rows, columnId, direction = 'asc') {
  const list = Array.isArray(rows) ? rows : []
  const dir = direction === 'desc' ? -1 : 1
  const keyOf = (row) => {
    const v = isObject(row) && isObject(row.sort) ? row.sort[columnId] : null
    return v === undefined ? null : v
  }
  return list
    .map((row, index) => ({ row, index, key: keyOf(row) }))
    .sort((a, b) => {
      const an = a.key === null
      const bn = b.key === null
      if (an || bn) return an && bn ? a.index - b.index : an ? 1 : -1
      let cmp = 0
      if (typeof a.key === 'number' && typeof b.key === 'number') cmp = a.key - b.key
      else cmp = String(a.key) < String(b.key) ? -1 : String(a.key) > String(b.key) ? 1 : 0
      return cmp !== 0 ? cmp * dir : a.index - b.index
    })
    .map((entry) => entry.row)
}

/** The next sort state after activating a column's header. */
export function nextSort(current, columnId) {
  const c = isObject(current) ? current : {}
  if (c.column === columnId) return { column: columnId, direction: c.direction === 'asc' ? 'desc' : 'asc' }
  return { column: columnId, direction: 'asc' }
}

/** `aria-sort` for a column header. */
export function ariaSort(sort, columnId) {
  if (!isObject(sort) || sort.column !== columnId) return 'none'
  return sort.direction === 'desc' ? 'descending' : 'ascending'
}

// ---------------------------------------------------------------- exports

/** The `/risk-map` response verbatim as GeoJSON text (it is a
 * FeatureCollection already); null when there is no response. */
export function sitesGeoJson(riskMap) {
  if (!isObject(riskMap)) return null
  return `${JSON.stringify(riskMap, null, 2)}\n`
}

export const SITES_CSV_FILENAME = 'monitoring-sites.csv'
export const SITES_GEOJSON_FILENAME = 'monitoring-sites.geojson'

/** The two `/sites` export buttons' builders (called on click). */
export function sitesExports(riskMap) {
  if (!isObject(riskMap)) return null
  return {
    csv: { filename: SITES_CSV_FILENAME, type: 'text/csv;charset=utf-8', content: () => sitesCsv(riskMap, { bom: true }) },
    geojson: { filename: SITES_GEOJSON_FILENAME, type: 'application/geo+json;charset=utf-8', content: () => sitesGeoJson(riskMap) },
  }
}

// ------------------------------------------------------------- list model

function requestOf(req) {
  const r = isObject(req) ? req : {}
  return { loading: r.loading === true, error: hasValue(r.error) ? r.error : null }
}

/** The server disclaimer to show with these data, verbatim. */
function disclaimerOf(payload, endpoint) {
  return isObject(payload) && text(payload.disclaimer) ? { text: payload.disclaimer, endpoint } : null
}

/**
 * The `/sites` page model.
 * @param {{riskMap?: object|null, request?: {loading?: boolean, error?: any}, sort?: {column, direction}|null}} input
 *   `sort` null (or unknown) keeps the API's order.
 * @returns {{state: 'loading'|'error'|'empty'|'stale'|'ready', rows, columns, sort, baseline, notes, exports, error, disclaimer}}
 */
export function buildSitesModel(input) {
  const { riskMap, request, sort } = isObject(input) ? input : {}
  const req = requestOf(request)
  const baseline = siteBaseline(riskMap)
  const columns = SITE_COLUMNS.filter((c) => !c.testOnly || baseline.present)
  const sortState = isObject(sort) && columns.some((c) => c.id === sort.column) && SORT_DIRECTIONS.includes(sort.direction)
    ? { column: sort.column, direction: sort.direction }
    : DEFAULT_SORT
  const base = { rows: [], columns, sort: sortState, baseline, notes: [], exports: null, error: null, disclaimer: null }
  if (!isObject(riskMap)) {
    return req.loading
      ? { ...base, state: 'loading' }
      : { ...base, state: 'error', error: { endpoint: '/risk-map', error: req.error } }
  }
  const features = Array.isArray(riskMap.features) ? riskMap.features.filter(isObject) : []
  const exports = sitesExports(riskMap)
  const disclaimer = disclaimerOf(riskMap, '/risk-map')
  if (features.length === 0) {
    return { ...base, state: 'empty', exports, disclaimer, notes: [msg('sites.empty')] }
  }
  const apiOrder = features.map((f) => buildSiteRow(f, baseline))
  const rows = sortState ? sortRows(apiOrder, sortState.column, sortState.direction) : apiOrder
  const withReading = rows.filter((r) => r.status === 'ok').length
  const staleCount = rows.filter((r) => r.stale).length
  const notes = [msg('sites.note.readings', { n: String(withReading), total: String(rows.length) })]
  if (staleCount > 0) notes.push({ ...msg('sites.note.stale', { n: String(staleCount), total: String(rows.length) }), tone: 'attention' })
  if (baseline.isTest) notes.push(msg('sites.note.test', { version: baseline.version ?? NULL_TEXT }))
  else if (baseline.present) notes.push({ ...msg('sites.note.test_invalid', { reason: baseline.reason ?? NULL_TEXT }), tone: 'attention' })
  return { ...base, state: staleCount > 0 ? 'stale' : 'ready', rows, notes, exports, disclaimer }
}

// ----------------------------------------------------------- detail model

/** The feature with `properties.site_id === siteId`, or null. */
export function findSite(riskMap, siteId) {
  if (!isObject(riskMap) || !Array.isArray(riskMap.features) || typeof siteId !== 'string' || siteId === '') return null
  return riskMap.features.find((f) => isObject(f) && isObject(f.properties) && f.properties.site_id === siteId) ?? null
}

/** `[lat, lng]` of a site feature, or nulls (GeoJSON order is [lng, lat]). */
export function siteCoords(feature) {
  const c = isObject(feature) && isObject(feature.geometry) && Array.isArray(feature.geometry.coordinates)
    ? feature.geometry.coordinates : []
  return { lat: finite(c[1]) ? c[1] : null, lng: finite(c[0]) ? c[0] : null }
}

const IMAGE_KINDS = Object.freeze([
  Object.freeze({ id: 'true_color', field: 'true_color_image_url', titleKey: 'site.image.true_color', altKey: 'site.image.alt_true_color' }),
  Object.freeze({ id: 'ndci_heatmap', field: 'ndci_heatmap_image_url', titleKey: 'site.image.ndci', altKey: 'site.image.alt_ndci' }),
])

/** The two cached images of a reading. No URL -> `absent` with the stated
 * reason: the server's `image_status` when the response has one, else
 * "no cached image" (plus the site's own status when it has no reading). */
function imagesOf(feature, props) {
  return IMAGE_KINDS.map((k) => {
    const url = text(props[k.field])
    const imageStatus = text(props.image_status)
    let absent = null
    if (!url) {
      absent = {
        key: 'site.image.absent',
        serverStatus: imageStatus,
        statusReason: !imageStatus && props.status !== 'ok' ? siteNullReason(props).code : null,
      }
    }
    return {
      id: k.id,
      titleKey: k.titleKey,
      altKey: k.altKey,
      url,
      date: val(props.actual_date, { kind: 'date', reason: siteNullReason(props).code }),
      cloud: val(props.cloud_fraction, { kind: 'percent', reason: siteNullReason(props).code }),
      source: refForSiteField(feature, k.field),
      dateSource: refForSiteField(feature, 'actual_date'),
      cloudSource: refForSiteField(feature, 'cloud_fraction'),
      absent,
    }
  })
}

/** The TEST anomaly block of one site: 'off' (no baseline block), 'invalid'
 * (mode test, baseline unusable) or 'test'. Support is
 * `baseline.min_season_dates_by_location[site_id]`. */
function anomalyBlock(feature, props, baseline) {
  if (!baseline.present) return { state: 'off' }
  const cell = anomalyCell(feature, baseline)
  const id = typeof props.site_id === 'string' ? props.site_id : null
  const byLocation = isObject(baseline.block.min_season_dates_by_location) ? baseline.block.min_season_dates_by_location : null
  const support = byLocation && id !== null && Object.hasOwn(byLocation, id) ? byLocation[id] : null
  const supportRef = (field, value) => sourceRef({
    endpoint: '/risk-map', field, value, unit: 'count', observedDate: null, runId: null, sceneId: null, formulaKey: 'robust_z', params: null,
  })
  return {
    state: baseline.isTest ? 'test' : 'invalid',
    reason: baseline.reason,
    chip: cell.chip,
    z: cell.z,
    zSource: cell.zSource,
    levelSource: cell.levelSource,
    reasonCode: cell.reasonCode,
    version: baseline.version ?? NULL_TEXT,
    support: val(support, { kind: 'count', reason: byLocation ? 'site_not_in_baseline' : 'not_available' }),
    supportSource: supportRef(`baseline.min_season_dates_by_location.${id ?? NULL_TEXT}`, support),
    declaredMin: val(baseline.block.min_independent_dates, { kind: 'count' }),
    declaredMinSource: supportRef('baseline.min_independent_dates', baseline.block.min_independent_dates),
    seasonRule: text(baseline.block.season_rule),
    history: formatDateSpan(text(baseline.block.history_start), text(baseline.block.history_end)) ?? NULL_TEXT,
  }
}

/** Was this request given up on the client because it took too long? */
export function isTimeout(error) {
  if (error === null || typeof error !== 'object') return false
  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') return true
  return typeof error.message === 'string' && /timeout/i.test(error.message)
}

/** The table rows of a `/timeseries` response: one per API point, same
 * numbers, same order; `raw` is the point itself. */
export function modisRows(timeseries) {
  const points = isObject(timeseries) && Array.isArray(timeseries.points) ? timeseries.points : []
  return points.map((p, i) => {
    const point = isObject(p) ? p : {}
    const reason = text(point.reason) ?? 'not_available'
    return {
      key: `${plain(point.date)}-${i}`,
      raw: p,
      date: val(point.date, { kind: 'date' }),
      chlor: val(point.chlor_a, { kind: 'mg-m3' }),
      z: val(point.anomaly_z, { kind: 'z', reason }),
      reasonText: text(point.reason),
    }
  })
}

/** Chart points: time (epoch ms, for the axis) and the two API values, each
 * left null when the API has none -- a null is never drawn as 0. */
export function modisChartData(timeseries) {
  const points = isObject(timeseries) && Array.isArray(timeseries.points) ? timeseries.points : []
  return points
    .filter(isObject)
    .map((p) => ({ t: toUtcMs(p.date), date: text(p.date), chlor_a: finite(p.chlor_a) ? p.chlor_a : null, anomaly_z: finite(p.anomaly_z) ? p.anomaly_z : null }))
    .filter((p) => p.t !== null)
}

/** The MODIS block of the detail page. A failure here degrades this block
 * only. `methods` is the `/methods` response (or null). */
export function buildModisModel(input) {
  const { timeseries, request, methods, lat, lng, siteId } = isObject(input) ? input : {}
  const req = requestOf(request)
  const modis = isObject(methods) && isObject(methods.modis) ? methods.modis : null
  const params = { lat, lng }
  const ref = (field, value, unit) => sourceRef({
    endpoint: '/timeseries', field, value, unit, observedDate: null, runId: null, sceneId: null, formulaKey: null, params,
  })
  const resolution = {
    value: val(modis ? modis.grid_resolution_m : null, { kind: 'count', unit: 'm', reason: 'not_available' }),
    source: sourceRef({
      endpoint: '/methods', field: 'modis.grid_resolution_m', value: modis ? modis.grid_resolution_m : null, unit: 'm',
      observedDate: null, runId: null, sceneId: null, formulaKey: null, params: null,
    }),
    collection: modis ? text(modis.collection) : null,
    recordStart: modis ? text(modis.record_start) : null,
  }
  const endpoint = requestPath('/timeseries', params)
  const base = {
    endpoint, resolution, rows: [], chart: [], count: 0, zMissing: 0, span: NULL_TEXT,
    sourceText: null, csv: null, source: null, zSource: null, error: null, timeoutSeconds: TIMESERIES_TIMEOUT_MS / 1000,
  }
  if (!finite(lat) || !finite(lng)) return { ...base, state: 'empty', empty: msg('site.modis.no_coords') }
  if (!isObject(timeseries)) {
    if (req.loading || !req.error) return { ...base, state: 'loading' }
    return { ...base, state: isTimeout(req.error) ? 'timeout' : 'error', error: { endpoint, error: req.error } }
  }
  const rows = modisRows(timeseries)
  const points = Array.isArray(timeseries.points) ? timeseries.points.filter(isObject) : []
  const dates = points.map((p) => text(p.date)).filter(Boolean)
  const span = dates.length ? formatDateSpan(dates[0], dates[dates.length - 1]) : NULL_TEXT
  const file = `modis-chlor_a-${typeof siteId === 'string' && siteId ? siteId : `${plain(lat)}_${plain(lng)}`}.csv`
  const ready = {
    ...base,
    rows,
    chart: modisChartData(timeseries),
    count: rows.length,
    zMissing: points.filter((p) => !finite(p.anomaly_z)).length,
    span,
    first: dates[0] ?? NULL_TEXT,
    last: dates[dates.length - 1] ?? NULL_TEXT,
    sourceText: text(timeseries.source),
    csv: { filename: file, content: () => timeseriesCsv(timeseries, { bom: true }) },
    source: ref('points[].chlor_a', null, MG_M3),
    zSource: ref('points[].anomaly_z', null, 'dimensionless'),
    disclaimer: disclaimerOf(timeseries, '/timeseries'),
  }
  if (rows.length === 0) return { ...ready, state: 'empty', empty: msg('site.modis.empty') }
  return { ...ready, state: 'ready' }
}

/**
 * The `/sites/:siteId` page model.
 * @param {{riskMap?, siteId?, request?, timeseries?, timeseriesRequest?, methods?}} input
 * @returns {{state: 'loading'|'error'|'not_found'|'ready', ...}}
 */
export function buildSiteDetailModel(input) {
  const { riskMap, siteId, request, timeseries, timeseriesRequest, methods } = isObject(input) ? input : {}
  const req = requestOf(request)
  if (!isObject(riskMap)) {
    return req.loading
      ? { state: 'loading', siteId: plain(siteId) }
      : { state: 'error', siteId: plain(siteId), error: { endpoint: '/risk-map', error: req.error } }
  }
  const feature = findSite(riskMap, siteId)
  if (!feature) return { state: 'not_found', siteId: plain(siteId) }

  const props = isObject(feature.properties) ? feature.properties : {}
  const baseline = siteBaseline(riskMap)
  const row = buildSiteRow(feature, baseline)
  const { lat, lng } = siteCoords(feature)
  const why = siteNullReason(props)
  const iv = isObject(props.index_values) ? props.index_values : null

  return {
    state: 'ready',
    siteId: row.id,
    name: row.name,
    chips: row.chips,
    status: row.status,
    isStale: row.stale,
    coords: { lat: row.cells.lat, lng: row.cells.lng, latSource: row.sources.lat, lngSource: row.sources.lng },
    lat,
    lng,
    rawUrl: apiAssetUrl('/risk-map'),
    statusNote: props.status === 'ok' ? null : { reasonCode: why.code, serverText: text(props.error) },
    reading: [
      { id: 'actual_date', labelKey: 'site.reading.actual_date', value: row.cells.actual_date, source: row.sources.actual_date },
      { id: 'cloud_fraction', labelKey: 'site.reading.cloud_fraction', value: row.cells.cloud_fraction, source: row.sources.cloud_fraction },
      { id: 'fetched_at', labelKey: 'site.reading.fetched_at', value: row.cells.fetched_at, source: row.sources.fetched_at },
    ],
    indexUsed: { text: row.indexUsed, source: row.sources.index_used },
    staleSource: row.sources.stale,
    confidenceLabel: text(props.confidence_label),
    images: imagesOf(feature, props),
    indices: SITE_INDEX_FIELDS.map((f) => ({
      key: f.key,
      label: f.label,
      href: `/methods#${f.key}`,
      used: row.indexUsed === f.key,
      value: row.cells[f.key],
      source: row.sources[f.key],
      reasonText: !iv ? why.text : null,
    })),
    anomaly: anomalyBlock(feature, props, baseline),
    modis: buildModisModel({ timeseries, request: timeseriesRequest, methods, lat, lng, siteId: row.id }),
    disclaimer: disclaimerOf(riskMap, '/risk-map'),
  }
}
