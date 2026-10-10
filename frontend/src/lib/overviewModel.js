/**
 * buildOverviewModel: everything the Overview page (`/`) shows, as data --
 * i18n keys with already-formatted params, formatted values, status-chip
 * descriptors, source refs and one state per block -- so the page is a thin
 * renderer and every rule here runs under `node --test` (dashboard spec
 * §4.1, §4.6, §10; test-baseline spec §6, §7).
 *
 * Data source (all read-only, nothing computed that the API did not send):
 *   - `GET /raster-scan` (RasterScanResponse): newest_scene_date, coverage,
 *     scene_count, scene_dates, bounds, legend, overlay_url, stale_run_id,
 *     latest_scene, last_used_scene_date, poll;
 *   - `GET /summary` (SummaryResponse): total_sites, risk_level_counts,
 *     stale_site_count, baseline;
 *   - `GET /risk-map` (RiskMapResponse): the seven site features;
 *   - `GET /raster-scan/highlights?n=5&run_id=<served run>`
 *     (RasterHighlightsResponse / RasterAnomalyHighlightsResponse);
 *   - the baseline state from useBaseline() (`/methods`), for the TEST lines
 *     and `latest_scene_policy.settle_hours`.
 *
 * Output: see `buildOverviewModel` below. Every message is `{key, params}`
 * (a param may itself be a message; `renderMessage` resolves it); every
 * displayed value is `{raw, spec, text, isNull, reason}` from formatValue,
 * so an unknown is "—" with a reason, never 0, and a real zero stays 0.
 *
 * Block states: 'loading' | 'error' | 'empty' | 'stale' | 'ready' (first
 * match wins). Pins add 'no_raster' | 'other_run' | 'unknown_mode'.
 *
 * Rules kept here:
 *   - no client-side science: the only arithmetic is formatting, counts of
 *     rows, sums of API counts, and placing pins on the figure from the
 *     raster's own bounds (layout);
 *   - a failing, never-run or old poll means newer scenes MAY exist
 *     unchecked (classifyPoll, shared with the banner) -- nothing here says
 *     "no newer scene";
 *   - `not_checked_yet` and `no_usable_data` stay two separate rows;
 *   - pins are drawn only when they belong to the raster shown; anomaly-mode
 *     pins are always TEST; no pin carries a risk tier.
 *
 * Limitations: pure function of its inputs (pass `now`). It does not fetch,
 * and it never decides what a reading means.
 */
import { apiAssetUrl } from '../api/client.js'
import { formatValue, formatDateSpan, NULL_TEXT, NBSP } from './format.js'
import { deriveBanner, classifyPoll } from './statusBanner.js'
import { chipForSite, chipForAnomalyLevel, chipForStatus, STATUS } from './statusChip.js'
import { sourceRef, refForRasterField, refForSiteField, requestPath } from './provenance.js'
import { pinsCsv } from './csv.js'
import { encodeView } from './permalink.js'

/** Pins asked of `/raster-scan/highlights` for the preview (spec §4.6: top 5). */
export const PIN_COUNT = 5

export const BLOCK_STATES = Object.freeze(['loading', 'error', 'empty', 'stale', 'ready'])

const TIER_KEYS = Object.freeze(['normal', 'elevated', 'watch', 'warning'])
const HEX_COLOUR = /^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i
const MINUTE_MS = 60000

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)
const finite = (v) => typeof v === 'number' && Number.isFinite(v)
const hasValue = (v) => v !== null && v !== undefined
const msg = (key, params = {}) => ({ key, params })
// A note the reader must not miss (rendered with emphasis); same shape.
const caveat = (key, params = {}) => ({ key, params, tone: 'attention' })

// Ids and API codes, verbatim ("—" when absent); never number-formatted.
const plain = (v) => ((finite(v) || (typeof v === 'string' && v !== '')) ? String(v) : NULL_TEXT)
const dateText = (v) => formatValue(v, { kind: 'date' }).text
const utcText = (v) => formatValue(v, { kind: 'datetime-utc' }).text
const countText = (v) => formatValue(v, { kind: 'count' }).text

/** One displayed value: the API value, its spec and formatValue's result. */
function val(raw, spec) {
  const r = formatValue(raw, spec)
  return { raw: hasValue(raw) ? raw : null, spec, text: r.text, isNull: r.isNull, reason: r.reason }
}

/** `{loading, error}` of one request; absent means settled without error. */
function request(requests, name) {
  const r = isObject(requests) && isObject(requests[name]) ? requests[name] : {}
  return { loading: r.loading === true, error: hasValue(r.error) ? r.error : null }
}

/** 'loading' | 'error' while a payload is missing, null once it is here. */
function missingState(payload, req) {
  if (isObject(payload)) return null
  return req.loading ? 'loading' : 'error'
}

/** Cloud and threshold as percentages. Two that would look equal ("50 % >
 * 50 %") get one decimal, then two, so the text never contradicts the
 * server's decision. Formatting only: the decision itself is the API's. */
function cloudPair(cloud, threshold) {
  for (const decimals of [0, 1, 2]) {
    const a = formatValue(cloud, { kind: 'percent', decimals }).text
    const b = formatValue(threshold, { kind: 'percent', decimals }).text
    if (a !== b || a === NULL_TEXT) return { cloud: a, threshold: b }
  }
  return {
    cloud: formatValue(cloud, { kind: 'percent', decimals: 2 }).text,
    threshold: formatValue(threshold, { kind: 'percent', decimals: 2 }).text,
  }
}

/** How long ago, as a message: under a minute, minutes (< 2 h), hours
 * (< 48 h), days. A negative age (clock skew) reads as under a minute. */
export function ageMessage(ageMs) {
  if (!finite(ageMs)) return msg('overview.age.unknown')
  const minutes = Math.floor(Math.max(0, ageMs) / MINUTE_MS)
  if (minutes < 1) return msg('overview.age.under_minute')
  if (minutes < 120) return msg('overview.age.minutes', { n: String(minutes) })
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return msg('overview.age.hours', { n: String(hours) })
  return msg('overview.age.days', { n: String(Math.floor(hours / 24)) })
}

/** A message as text through `t`, resolving params that are messages. */
export function renderMessage(t, message) {
  if (!isObject(message) || typeof message.key !== 'string' || typeof t !== 'function') return ''
  const params = {}
  for (const [name, value] of Object.entries(isObject(message.params) ? message.params : {})) {
    params[name] = isObject(value) && typeof value.key === 'string' ? renderMessage(t, value) : value
  }
  return t(message.key, params)
}

// ------------------------------------------------------------- key facts

function rasterCardState(raster, req) {
  const missing = missingState(raster, req)
  if (missing) return missing
  if (!hasValue(raster.run_id)) return 'empty'
  return hasValue(raster.stale_run_id) ? 'stale' : 'ready'
}

function staleRasterNote(raster) {
  return caveat('overview.stale.raster', { run: plain(raster.run_id), stale_run: plain(raster.stale_run_id) })
}

function card(id, titleKey, state, extra) {
  return {
    id, titleKey, state, value: val(null, { kind: 'count' }), unit: null, notes: [], chips: [],
    breakdown: [], link: null, source: null, error: null, ...extra,
  }
}

// The field each raster card reads, for its source chip when it is empty.
const EMPTY_FIELDS = Object.freeze({
  newest_scene: 'newest_scene_date', measured_area: 'coverage.measured_fraction', scenes: 'scene_count',
})

function rasterCards(raster, req, pollHealth) {
  const state = rasterCardState(raster, req)
  const ids = [
    ['newest_scene', 'overview.fact.newest_scene', { kind: 'date' }],
    ['measured_area', 'overview.fact.measured_area', { kind: 'percent', decimals: 1 }],
    ['scenes', 'overview.fact.scenes', { kind: 'count' }],
  ]
  if (state === 'loading' || state === 'error') {
    return ids.map(([id, titleKey, spec]) => card(id, titleKey, state, {
      value: val(null, spec),
      notes: [msg(state === 'loading' ? 'overview.state.raster_loading' : 'overview.state.raster_error')],
      error: state === 'error' ? { endpoint: '/raster-scan', error: req.error } : null,
    }))
  }
  if (state === 'empty') {
    return ids.map(([id, titleKey, spec]) => card(id, titleKey, 'empty', {
      value: val(null, spec),
      notes: [msg('overview.state.raster_empty')],
      source: refForRasterField(raster, EMPTY_FIELDS[id]),
    }))
  }

  const stale = state === 'stale'
  const staleExtra = stale ? { chips: [chipForStatus(STATUS.STALE)] } : {}
  const withStale = (notes) => (stale ? [...notes, staleRasterNote(raster)] : notes)

  // Newest scene date.
  const newestNotes = [msg('overview.fact.newest_scene_note', {
    run: plain(raster.run_id), date_used: dateText(raster.date_used), oldest: dateText(raster.oldest_scene_date),
  })]
  if (pollHealth !== 'ok') newestNotes.push(caveat('overview.fact.newest_scene_unchecked'))
  const newest = card('newest_scene', 'overview.fact.newest_scene', state, {
    value: val(raster.newest_scene_date, { kind: 'date' }),
    notes: withStale(newestNotes),
    source: refForRasterField(raster, 'newest_scene_date'),
    ...staleExtra,
  })

  // Measured area: share of the study POLYGON (land included), not of water.
  const coverage = isObject(raster.coverage) ? raster.coverage : null
  const fraction = coverage ? coverage.measured_fraction : null
  const measuredNotes = []
  if (!coverage || !finite(fraction)) {
    measuredNotes.push(caveat('overview.fact.coverage_unknown'))
  } else if (finite(coverage.measured_pixels) && finite(coverage.polygon_pixels)) {
    measuredNotes.push(msg('overview.fact.measured_pixels', {
      measured: countText(coverage.measured_pixels), polygon: countText(coverage.polygon_pixels),
    }))
  } else {
    measuredNotes.push(msg('overview.fact.measured_pixels_unknown', { polygon: countText(coverage.polygon_pixels) }))
  }
  measuredNotes.push(caveat('overview.fact.not_measured_note'))
  const measured = card('measured_area', 'overview.fact.measured_area', finite(fraction) ? state : 'empty', {
    value: val(fraction, { kind: 'percent', decimals: 1 }),
    unit: msg('overview.fact.measured_unit'),
    notes: withStale(measuredNotes),
    source: refForRasterField(raster, 'coverage.measured_fraction'),
    ...staleExtra,
  })

  // Scenes mixed into the one mosaic.
  const days = Array.isArray(raster.scene_dates) ? raster.scene_dates.filter(isObject) : null
  const sceneNotes = []
  if (days && days.length > 0) {
    sceneNotes.push(msg('overview.fact.scenes_days', {
      days: countText(days.length),
      span: formatDateSpan(raster.oldest_scene_date, raster.newest_scene_date) ?? NULL_TEXT,
    }))
    const largest = days.filter((d) => finite(d.share)).sort((a, b) => b.share - a.share)[0]
    if (largest) {
      sceneNotes.push(msg('overview.fact.scenes_share', {
        date: dateText(largest.date), share: formatValue(largest.share, { kind: 'percent', decimals: 1 }).text,
      }))
    }
  } else {
    sceneNotes.push(caveat('overview.fact.scenes_days_unknown'))
  }
  sceneNotes.push(msg('overview.fact.scenes_note'))
  const scenes = card('scenes', 'overview.fact.scenes', state, {
    value: val(raster.scene_count, { kind: 'count' }),
    unit: msg('overview.fact.scenes_unit'),
    notes: withStale(sceneNotes),
    link: { to: '/map', key: 'overview.fact.scenes_link' },
    source: refForRasterField(raster, 'scene_count'),
    ...staleExtra,
  })

  return [newest, measured, scenes]
}

// The two "no reading" counts, always two rows: a site the scheduler read
// without a usable value is a finding; one it has not reached is a loading
// state (RiskLevelCounts). Never summed into one figure.
const BREAKDOWN = Object.freeze([STATUS.NO_USABLE_DATA, STATUS.NOT_CHECKED_YET])

function summaryRef(field, value) {
  return sourceRef({ endpoint: '/summary', field, value, unit: 'count' })
}

function sitesCard(summary, req) {
  const missing = missingState(summary, req)
  const emptyBreakdown = () => BREAKDOWN.map((id) => ({
    id, chip: chipForStatus(id), labelKey: `status.${id}`, value: val(null, { kind: 'count' }), source: null,
  }))
  if (missing) {
    return card('sites', 'overview.fact.sites', missing, {
      notes: [msg(missing === 'loading' ? 'overview.state.summary_loading' : 'overview.state.summary_error')],
      breakdown: emptyBreakdown(),
      error: missing === 'error' ? { endpoint: '/summary', error: req.error } : null,
    })
  }
  const counts = isObject(summary.risk_level_counts) ? summary.risk_level_counts : {}
  const total = finite(summary.total_sites) ? summary.total_sites : null
  // Sites with a reading: not_evaluated plus any tier count (all API counts;
  // an absent one makes the sum unknown rather than a guessed 0).
  const parts = ['not_evaluated', ...TIER_KEYS].map((k) => counts[k])
  const usable = parts.every(finite) ? parts.reduce((a, b) => a + b, 0) : null
  const tiers = TIER_KEYS.every((k) => finite(counts[k])) ? TIER_KEYS.reduce((a, k) => a + counts[k], 0) : null

  const breakdown = BREAKDOWN.map((id) => ({
    id,
    chip: chipForStatus(id),
    labelKey: `status.${id}`,
    value: val(counts[id], { kind: 'count' }),
    source: summaryRef(`risk_level_counts.${id}`, counts[id]),
  }))

  const notes = []
  let state = 'ready'
  if (total === null || total === 0) {
    state = 'empty'
    notes.push(msg('overview.state.summary_empty'))
  } else {
    notes.push(msg('overview.fact.sites_note'))
  }
  if (finite(tiers) && tiers > 0) {
    notes.push(caveat('banner.tiers_not_shown', { tiers: countText(tiers), total: countText(total) }))
  }
  const chips = []
  if (finite(summary.stale_site_count) && summary.stale_site_count > 0) {
    if (state === 'ready') state = 'stale'
    chips.push(chipForStatus(STATUS.STALE))
    notes.push(caveat('overview.stale.sites', { n: countText(summary.stale_site_count), total: countText(total) }))
  }
  const field = finite(tiers) && tiers > 0
    ? 'risk_level_counts.not_evaluated + normal + elevated + watch + warning'
    : 'risk_level_counts.not_evaluated'
  return card('sites', 'overview.fact.sites', state, {
    value: val(usable, { kind: 'count' }),
    unit: msg('overview.fact.sites_unit', { total: countText(total) }),
    notes,
    chips,
    breakdown,
    source: summaryRef(field, usable),
  })
}

// ---------------------------------------------------- scene and poll lines

/** The latest-scene line (also used by the /map rail, src/lib/mapModel.js). */
export function latestSceneBlock(raster, req, methods) {
  const missing = missingState(raster, req)
  const source = isObject(raster) ? refForRasterField(raster, 'latest_scene') : null
  if (missing) {
    return {
      state: missing, tone: 'neutral', line: msg(missing === 'loading' ? 'overview.state.raster_loading' : 'overview.state.raster_error'),
      notes: [], serverReason: null, source: null,
      error: missing === 'error' ? { endpoint: '/raster-scan', error: req.error } : null,
    }
  }
  const scene = isObject(raster.latest_scene) ? raster.latest_scene : null
  if (!scene) {
    return { state: 'empty', tone: 'neutral', line: msg('overview.scene.none'), notes: [], serverReason: null, source, error: null }
  }
  const date = dateText(scene.acquisition_date)
  const pair = cloudPair(scene.cloud_fraction, scene.threshold_cloud_fraction)
  const run = plain(scene.used_in_run_id)
  let line
  let inShown = false
  if (scene.reassessed_after_use === true) {
    line = scene.decision === 'rejected_cloud'
      ? msg('overview.scene.reassessed_cloud', { date, run, ...pair })
      : msg('overview.scene.reassessed_other', { date, run, decision: plain(scene.decision) })
    inShown = scene.used_in_served_run === true
  } else if (scene.decision === 'passed') {
    if (scene.used_in_served_run === true) {
      line = msg('overview.scene.used', { date, ...pair })
      inShown = true
    } else if (hasValue(scene.used_in_run_id)) {
      line = msg('overview.scene.used_other_run', { date, run, ...pair })
    } else {
      line = msg('overview.scene.pending', { date, ...pair })
    }
  } else if (scene.decision === 'rejected_cloud') {
    line = msg('overview.scene.rejected_cloud', { date, ...pair })
  } else if (scene.decision === 'rejected_no_water') {
    line = msg('overview.scene.rejected_no_water', { date, min: countText(scene.min_water_pixels) })
  } else {
    line = msg('overview.scene.not_used', { date, decision: plain(scene.decision) })
  }

  const notes = []
  if (!inShown) {
    notes.push(hasValue(raster.run_id)
      ? msg('overview.scene.shown', { run: plain(raster.run_id), shown: dateText(raster.newest_scene_date) })
      : msg('overview.scene.no_raster'))
  }
  const settleHours = isObject(methods) && isObject(methods.latest_scene_policy)
    ? methods.latest_scene_policy.settle_hours : null
  if (scene.settled === true) {
    notes.push(finite(settleHours)
      ? msg('overview.scene.settled_hours', { hours: countText(settleHours) })
      : msg('overview.scene.settled'))
  } else {
    notes.push(msg('overview.scene.provisional'))
  }
  notes.push(msg('overview.scene.assessed_at', { at: utcText(scene.assessed_at) }))

  return {
    state: 'ready',
    tone: inShown && scene.reassessed_after_use !== true ? 'neutral' : 'attention',
    line,
    notes,
    serverReason: typeof scene.reason === 'string' && scene.reason.trim() !== '' ? scene.reason : null,
    source,
    error: null,
  }
}

/** The newer-scene poll line (also used by the /map rail). */
export function pollBlock(raster, req, nowMs) {
  const missing = missingState(raster, req)
  if (missing) {
    return {
      state: missing, health: null, tone: 'neutral',
      line: msg(missing === 'loading' ? 'overview.state.raster_loading' : 'overview.state.raster_error'),
      notes: [], serverText: null, source: null,
      error: missing === 'error' ? { endpoint: '/raster-scan', error: req.error } : null,
    }
  }
  const poll = isObject(raster.poll) ? raster.poll : null
  const health = classifyPoll(poll, nowMs)
  const source = refForRasterField(raster, 'poll')
  const lastOk = utcText(poll?.last_poll_ok_at)
  const age = ageMessage(health.ageMs)
  const notes = []
  let line
  if (health.state === 'failing') {
    line = health.okMs === null
      ? msg('overview.poll.failing_never_ok', { kind: plain(poll.last_error_kind), since: utcText(poll.last_error_at) })
      : msg('overview.poll.failing', { kind: plain(poll.last_error_kind), since: utcText(poll.last_error_at), last_ok: lastOk, age })
  } else if (health.state === 'never') {
    line = msg('overview.poll.never')
  } else if (health.state === 'old') {
    line = msg('overview.poll.old', { last_ok: lastOk, age })
  } else {
    line = msg('overview.poll.ok', { last_ok: lastOk, age })
    notes.push(msg('overview.poll.ok_note'))
  }
  if (health.state !== 'failing' && poll && hasValue(poll.last_error)) {
    notes.push(msg('overview.poll.recovered', { kind: plain(poll.last_error_kind), at: utcText(poll.last_error_at) }))
  }
  const failingText = health.state === 'failing' && typeof poll.last_error === 'string' && poll.last_error.trim() !== ''
    ? poll.last_error : null
  return {
    state: poll ? 'ready' : 'empty',
    health: health.state,
    tone: health.state === 'ok' ? 'neutral' : 'attention',
    line,
    notes,
    serverText: failingText,
    source,
    error: null,
  }
}

// ------------------------------------------------------------ map preview

/** `[[south, west], [north, east]]` -> edges, or null when unusable. */
function edges(bounds) {
  if (!Array.isArray(bounds) || bounds.length !== 2 || !bounds.every((p) => Array.isArray(p) && p.length === 2)) return null
  const [[south, west], [north, east]] = bounds
  if (![south, west, north, east].every(finite) || north <= south || east <= west) return null
  return { south, west, north, east }
}

/** Percent position of a coordinate on the figure (layout only: the
 * overlay PNG is a regular latitude-longitude grid, row 0 north). */
function place(box, lat, lng) {
  if (!box || !finite(lat) || !finite(lng)) return { x: null, y: null, inFigure: false }
  const x = ((lng - box.west) / (box.east - box.west)) * 100
  const y = ((box.north - lat) / (box.north - box.south)) * 100
  return { x, y, inFigure: x >= 0 && x <= 100 && y >= 0 && y <= 100 }
}

const coordText = (v) => formatValue(v, { kind: 'coord', decimals: 2, unit: '°' }).text

function legendFrom(raster) {
  const value = isObject(raster.legend) && isObject(raster.legend.value) ? raster.legend.value : {}
  const swatches = (Array.isArray(value.swatches) ? value.swatches : [])
    .filter((s) => isObject(s) && typeof s.hex === 'string' && HEX_COLOUR.test(s.hex))
    .map((s) => ({ hex: s.hex, value: finite(s.value) ? s.value : null }))
  const domain = Array.isArray(value.domain) && value.domain.length === 2 && value.domain.every(finite) ? value.domain : null
  // The renderer clamps outside the domain (render.ramp_rgb), so the end
  // colours also stand for every value beyond them.
  const end = (sign, v) => `${sign}${NBSP}${formatValue(v, { kind: 'index' }).text}`
  return {
    swatches,
    min: domain ? end('≤', domain[0]) : null,
    max: domain ? end('≥', domain[1]) : null,
    serverMeaning: typeof value.meaning === 'string' && value.meaning.trim() !== '' ? value.meaning : null,
  }
}

/** The pins of the raster shown. `box` is null when there is no usable
 * raster (then no pins are asked for); `rasterLoading` says why. */
function pinsBlock(highlights, hlReq, raster, rasterLoading, box) {
  const runId = isObject(raster) ? raster.run_id : null
  const endpoint = requestPath('/raster-scan/highlights', { n: PIN_COUNT, run_id: runId })
  const base = {
    mode: null, isTest: false, headingKey: 'overview.pins.heading', legendKey: null, shape: null, items: [],
    notes: [], serverReason: null, empty: null, error: null, endpoint, csv: null,
  }
  if (!box) {
    return rasterLoading ? { ...base, state: 'loading' } : { ...base, state: 'no_raster', empty: msg('overview.pins.no_raster') }
  }
  const missing = missingState(highlights, hlReq)
  if (missing) {
    return { ...base, state: missing, error: missing === 'error' ? { endpoint, error: hlReq.error } : null }
  }
  if (highlights.run_id !== runId) {
    return { ...base, state: 'other_run', empty: msg('overview.pins.other_run', { pins_run: plain(highlights.run_id), run: plain(runId) }) }
  }
  const mode = highlights.mode
  if (mode !== 'ndci' && mode !== 'anomaly') {
    return { ...base, state: 'unknown_mode', empty: msg('overview.pins.unknown_mode', { mode: plain(mode) }) }
  }
  const isTest = mode === 'anomaly' // anomaly pins exist only against a TEST baseline
  const pins = (Array.isArray(highlights.pins) ? highlights.pins : []).filter((p) => isObject(p) && Number.isInteger(p.rank))
  const params = { n: PIN_COUNT, run_id: runId }
  const items = pins.map((p) => {
    const ndci = isObject(p.index_values) ? p.index_values.ndci : null
    const pos = place(box, p.pixel_centre_lat, p.pixel_centre_lng)
    return {
      rank: p.rank,
      ...pos,
      ndci: val(ndci, { kind: 'index' }),
      z: isTest ? val(p.robust_z, { kind: 'z' }) : null,
      chip: isTest ? chipForAnomalyLevel(p.anomaly_level, true) : null,
      date: val(p.acquired_date, { kind: 'date' }),
      edge: p.edge_of_no_data === true,
      href: `/map?${encodeView({ runId, pin: p.rank })}`,
      source: sourceRef({
        endpoint: '/raster-scan/highlights', params, field: `pins[rank=${p.rank}].index_values.ndci`, value: ndci,
        unit: 'dimensionless', observedDate: p.acquired_date, runId, formulaKey: 'ndci',
      }),
      zSource: isTest ? sourceRef({
        endpoint: '/raster-scan/highlights', params, field: `pins[rank=${p.rank}].robust_z`, value: p.robust_z,
        unit: 'dimensionless', observedDate: p.acquired_date, runId, formulaKey: 'robust_z',
      }) : null,
    }
  })
  const notes = []
  if (isTest && isObject(highlights.counts)) {
    const c = highlights.counts
    notes.push(msg('overview.pins.anomaly_counts', {
      assessable: countText(c.assessable),
      measured: countText(c.measured),
      flagged: finite(c.watch) && finite(c.high) ? countText(c.watch + c.high) : NULL_TEXT,
    }))
  }
  if (items.length > 0 && items.length < PIN_COUNT) {
    notes.push(msg('overview.pins.fewer', { count: countText(items.length), n: countText(PIN_COUNT) }))
  }
  if (items.some((p) => !p.inFigure)) notes.push(msg('overview.pins.outside_figure'))
  const serverReason = typeof highlights.reason === 'string' && highlights.reason.trim() !== '' ? highlights.reason : null
  return {
    ...base,
    state: items.length === 0 ? 'empty' : 'ready',
    mode,
    isTest,
    headingKey: isTest ? 'overview.pins.heading_anomaly' : 'overview.pins.heading_ndci',
    legendKey: isTest ? 'overview.pins.legend_anomaly' : 'overview.pins.legend_ndci',
    // The two pin kinds never share a marker shape (test-baseline spec §6).
    shape: isTest ? 'diamond' : 'square',
    items,
    notes,
    serverReason,
    empty: items.length === 0 ? msg('overview.pins.none') : null,
    csv: items.length > 0
      ? { filename: `highlight-pins-run-${plain(runId)}.csv`, content: () => pinsCsv(highlights, { bom: true }) }
      : null,
  }
}

function siteMarkers(riskMap, box) {
  const features = isObject(riskMap) && Array.isArray(riskMap.features) ? riskMap.features : []
  return features.filter(isObject).map((f) => {
    const props = isObject(f.properties) ? f.properties : {}
    const coords = isObject(f.geometry) && Array.isArray(f.geometry.coordinates) ? f.geometry.coordinates : []
    return { id: plain(props.site_id), name: typeof props.name === 'string' ? props.name : plain(props.site_id), ...place(box, coords[1], coords[0]) }
  }).filter((s) => s.inFigure)
}

function previewBlock(raster, req, highlights, hlReq, riskMap) {
  const state = rasterCardState(raster, req)
  const empty = { image: null, box: null, extent: null, caption: null, legend: null, sites: [], staleNote: null, source: null }
  if (state === 'loading' || state === 'error') {
    return {
      state, ...empty, empty: null, error: state === 'error' ? { endpoint: '/raster-scan', error: req.error } : null,
      pins: pinsBlock(null, hlReq, raster, state === 'loading', null),
    }
  }
  const box = state === 'empty' ? null : edges(raster.bounds)
  const url = state === 'empty' ? null : apiAssetUrl(raster.overlay_url)
  if (state === 'empty' || !box || !url) {
    return {
      state: 'empty', ...empty, error: null,
      empty: msg(state === 'empty' ? 'overview.state.raster_empty' : box ? 'overview.map.no_overlay' : 'overview.map.no_bounds'),
      pins: pinsBlock(null, hlReq, raster, false, null),
    }
  }
  const span = formatDateSpan(raster.oldest_scene_date, raster.newest_scene_date) ?? NULL_TEXT
  return {
    state,
    image: { url, alt: msg('overview.map.alt', { run: plain(raster.run_id), span }) },
    box: { ...box, aspect: (box.east - box.west) / (box.north - box.south) },
    extent: msg('overview.map.extent', {
      south: coordText(box.south), north: coordText(box.north), west: coordText(box.west), east: coordText(box.east),
    }),
    caption: msg('overview.map.caption', { run: plain(raster.run_id), span, scale: countText(raster.scale_m) }),
    legend: legendFrom(raster),
    sites: siteMarkers(riskMap, box),
    staleNote: state === 'stale' ? staleRasterNote(raster) : null,
    source: refForRasterField(raster, 'overlay_url'),
    empty: null,
    error: null,
    pins: pinsBlock(highlights, hlReq, raster, false, box),
  }
}

// ----------------------------------------------------------- sites strip

function sitesBlock(riskMap, req) {
  const missing = missingState(riskMap, req)
  if (missing) {
    return {
      state: missing, items: [], notes: [], empty: null,
      error: missing === 'error' ? { endpoint: '/risk-map', error: req.error } : null,
    }
  }
  const features = Array.isArray(riskMap.features) ? riskMap.features.filter(isObject) : []
  if (features.length === 0) {
    return { state: 'empty', items: [], notes: [], empty: msg('overview.state.sites_empty'), error: null }
  }
  const items = features.map((f) => {
    const props = isObject(f.properties) ? f.properties : {}
    const id = plain(props.site_id)
    // A site without a reading says why its date is "—": its own status.
    const reason = props.status !== 'ok' && typeof props.status === 'string' && props.status !== '' ? props.status : 'not_available'
    return {
      id,
      name: typeof props.name === 'string' && props.name !== '' ? props.name : id,
      chips: chipForSite(f),
      date: val(props.actual_date, { kind: 'date', reason }),
      href: `/sites/${encodeURIComponent(id)}`,
      source: refForSiteField(f, 'actual_date'),
    }
  })
  const staleCount = features.filter((f) => isObject(f.properties) && f.properties.stale === true).length
  const notes = staleCount > 0
    ? [caveat('overview.stale.sites_strip', { n: countText(staleCount), total: countText(features.length) })]
    : []
  return { state: staleCount > 0 ? 'stale' : 'ready', items, notes, empty: null, error: null }
}

// ------------------------------------------------------------ disclaimer

/** The server disclaimer to show, verbatim, from a response whose data is
 * on the page. The highlights first while their pins are drawn (in TEST
 * mode they carry the TEST variant, and their anomaly values are the
 * page's strongest statement), then /summary (it carries the baseline
 * block), /risk-map, /raster-scan. */
function pickDisclaimer(candidates) {
  for (const [endpoint, payload] of candidates) {
    if (isObject(payload) && typeof payload.disclaimer === 'string' && payload.disclaimer.trim() !== '') {
      return { text: payload.disclaimer, endpoint }
    }
  }
  return null
}

// ------------------------------------------------------------------ main

/**
 * @param {{raster?, summary?, riskMap?, highlights?, baseline?, now?: number|Date,
 *   requests?: {raster?, summary?, riskMap?, highlights?: {loading?: boolean, error?: any}}}} input
 *   Payloads are the API responses (or null); `requests` their request
 *   state. A missing payload that is not loading is an error.
 * @returns {{isTest, banner, facts, latestScene, poll, preview, sites, disclaimer}}
 */
export function buildOverviewModel(input) {
  const { raster, summary, riskMap, highlights, baseline, now, requests } = isObject(input) ? input : {}
  const nowMs = now instanceof Date ? now.getTime() : finite(now) ? now : Date.now()
  const req = {
    raster: request(requests, 'raster'),
    summary: request(requests, 'summary'),
    riskMap: request(requests, 'riskMap'),
    highlights: request(requests, 'highlights'),
  }
  const rasterData = isObject(raster) ? raster : null
  const summaryData = isObject(summary) ? summary : null
  const methods = isObject(baseline) && isObject(baseline.methods) ? baseline.methods : null
  // useBaseline() (/methods) once it knows the mode; until then, or when it
  // failed, the baseline block /summary carries (null = mode off).
  const known = isObject(baseline) && (baseline.isTest === true || baseline.mode === 'test' || baseline.mode === 'off')
  const baselineBlock = known ? baseline : summaryData && isObject(summaryData.baseline) ? summaryData.baseline : null
  const isTest = isObject(baselineBlock) && (baselineBlock.isTest === true || (baselineBlock.mode === 'test' && baselineBlock.valid === true))

  // The banner speaks once both of its sources have settled: a loading
  // summary must not read as "the summary could not be loaded".
  const bannerLoading = (!rasterData && req.raster.loading) || (!summaryData && req.summary.loading)
  const banner = bannerLoading
    ? { state: 'loading', key: 'overview.state.banner_loading', params: {}, tone: 'neutral', lines: [] }
    : { state: 'ready', ...deriveBanner({ raster: rasterData, summary: summaryData, baseline: baselineBlock, now: nowMs }) }

  const pollHealth = rasterData ? classifyPoll(rasterData.poll, nowMs).state : null
  const preview = previewBlock(rasterData, req.raster, isObject(highlights) ? highlights : null, req.highlights, riskMap)
  const pinsShown = preview.pins.state === 'ready' || preview.pins.state === 'empty'

  return {
    now: nowMs,
    isTest,
    banner,
    facts: [...rasterCards(rasterData, req.raster, pollHealth), sitesCard(summaryData, req.summary)],
    latestScene: latestSceneBlock(rasterData, req.raster, methods),
    poll: pollBlock(rasterData, req.raster, nowMs),
    preview,
    sites: sitesBlock(isObject(riskMap) ? riskMap : null, req.riskMap),
    disclaimer: pickDisclaimer([
      ['/raster-scan/highlights', pinsShown ? highlights : null],
      ['/summary', summaryData],
      ['/risk-map', riskMap],
      ['/raster-scan', rasterData],
    ]),
  }
}
