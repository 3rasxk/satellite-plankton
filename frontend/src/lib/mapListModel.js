/**
 * mapListModel: the data behind the glass chrome of the map page (`/map`)
 * and the shell's top bar -- the left card's headline, its count chips and
 * its station list, the default map layer, and the "Updated" freshness chip
 * -- as pure functions, so every rule runs under `node --test`.
 *
 * Data source (read-only; nothing computed that the API did not send):
 *   - `GET /risk-map` (RiskMapResponse): the seven fixed monitoring sites,
 *     read through src/lib/sitesModel.js `buildSiteRow` (status chips, NDCI,
 *     TEST anomaly cell) so the map and `/sites` can never disagree;
 *   - `GET /raster-scan/highlights` (the pins model of src/lib/mapModel.js
 *     and its raw `counts`): pin count and, in TEST anomaly mode only, the
 *     API's own watch/high counts;
 *   - `GET /raster-scan` (`poll`, `latest_scene`, `true_color_url`,
 *     `newest_scene_date`): the freshness chip and the default layer.
 *
 * Rules kept here:
 *   - the count chips name REAL categories only: sites measured / with no
 *     usable data / not checked yet / stale, and the API's TEST anomaly
 *     counts. There is no risk class and no client-side classification;
 *   - an unknown count is never 0: a chip whose number the API did not send
 *     is left out;
 *   - sorting: by robust z (TEST) descending while a valid TEST baseline
 *     gives at least one site an anomaly, unknowns last; otherwise by name.
 *     Stable, so equal keys keep the API's order;
 *   - the freshness dot is "ok" only when the newer-scene poll is healthy
 *     (statusBanner.classifyPoll: last success < 3 h old and no current
 *     error); everything else is "attention" with the Overview's own
 *     wording. Nothing here says that no newer scene exists.
 *
 * Limitations: pure functions of their inputs (pass `now`). They neither
 * fetch nor decide what a reading means.
 */
import { formatValue } from './format.js'
import { chipForStatus, chipForAnomalyLevel, STATUS } from './statusChip.js'
import { buildSiteRow, siteBaseline, siteCoords, sortRows } from './sitesModel.js'
import { classifyPoll } from './statusBanner.js'
import { ageMessage, pollBlock, latestSceneBlock } from './overviewModel.js'

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)
const finite = (v) => typeof v === 'number' && Number.isFinite(v)
const text = (v) => (typeof v === 'string' && v.trim() !== '' ? v : null)
const msg = (key, params = {}) => ({ key, params })
const countText = (v) => formatValue(v, { kind: 'count' }).text

/** Layer modes of the map page, in segmented-control order. */
export const LAYER_ORDER = Object.freeze(['true_color', 'ndci'])

/**
 * The layer a fresh visit opens on: True Color when the served run stored
 * its own Sentinel-2 RGB composite, else the NDCI raster. A permalink's
 * `layer` (validated by mapModel.applyPermalink) always wins over this.
 */
export function defaultLayer(raster) {
  return isObject(raster) && text(raster.true_color_url) ? 'true_color' : 'ndci'
}

/**
 * How a site is drawn on the map: 'reading' (status ok), 'not_checked'
 * (no_data_yet) or 'no_data' (any other status, including one this build
 * does not know -- never drawn as a reading).
 */
export function siteMarkerKind(status) {
  if (status === 'ok') return 'reading'
  if (status === 'no_data_yet') return 'not_checked'
  return 'no_data'
}

/**
 * The station list of the left card.
 * @param {{riskMap?: object|null, request?: {loading?, error?}}} input
 * @returns {{state: 'loading'|'error'|'empty'|'ready', items, sortedBy, counts, baseline, error}}
 *   `items[]`: { id, name, lat, lng, onMap, status, kind, stale, chips,
 *   primaryChip, ndci, anomaly, sources }.
 */
export function buildSiteListModel(input) {
  const { riskMap, request } = isObject(input) ? input : {}
  const req = isObject(request) ? request : {}
  const baseline = siteBaseline(riskMap)
  const base = { items: [], sortedBy: 'name', counts: null, baseline, error: null }
  if (!isObject(riskMap)) {
    if (req.error !== null && req.error !== undefined) return { ...base, state: 'error', error: { endpoint: '/risk-map', error: req.error } }
    return { ...base, state: 'loading' }
  }
  const features = Array.isArray(riskMap.features) ? riskMap.features.filter(isObject) : []
  if (features.length === 0) return { ...base, state: 'empty', counts: siteCounts([]) }

  const rows = features.map((f) => {
    const row = buildSiteRow(f, baseline)
    const { lat, lng } = siteCoords(f)
    return {
      id: row.id,
      name: row.name,
      lat,
      lng,
      onMap: lat !== null && lng !== null,
      status: row.status,
      kind: siteMarkerKind(row.status),
      stale: row.stale,
      chips: row.chips,
      primaryChip: row.chips[0] ?? chipForStatus(STATUS.NO_USABLE_DATA),
      ndci: row.cells.ndci,
      anomaly: row.anomaly,
      sources: row.sources,
      sort: row.sort,
    }
  })
  const anomalySort = baseline.isTest && rows.some((r) => r.anomaly.shown && finite(r.sort.anomaly))
  const items = anomalySort ? sortRows(rows, 'anomaly', 'desc') : sortRows(rows, 'name', 'asc')
  return { ...base, state: 'ready', items, sortedBy: anomalySort ? 'anomaly' : 'name', counts: siteCounts(rows) }
}

/** Site counts by the closed status vocabulary (never a risk class). */
export function siteCounts(items) {
  const list = Array.isArray(items) ? items : []
  return {
    total: list.length,
    measured: list.filter((r) => r.kind === 'reading').length,
    noUsable: list.filter((r) => r.kind === 'no_data').length,
    notChecked: list.filter((r) => r.kind === 'not_checked').length,
    stale: list.filter((r) => r.stale === true).length,
  }
}

/**
 * The left card's count chips: REAL categories only, each a status-chip
 * descriptor (so the words come from i18n `status.<key>`) plus the count.
 *   - TEST anomaly counts (`highlights.counts.watch` / `.high`), only while
 *     the pins of the run shown are in anomaly mode and the API sent them;
 *   - sites measured, then sites with no usable data, not checked yet and
 *     stale (each only when non-zero, except "measured").
 * @param {{sites?: object, pins?: object, highlights?: object|null}} input
 */
export function buildCountChips(input) {
  const { sites, pins, highlights } = isObject(input) ? input : {}
  const chips = []
  const pinsOfRun = isObject(pins) && (pins.state === 'ready' || pins.state === 'empty')
  if (pinsOfRun && pins.mode === 'anomaly' && isObject(highlights) && isObject(highlights.counts)) {
    for (const level of ['high', 'watch']) {
      const n = highlights.counts[level]
      if (finite(n)) {
        chips.push({ id: `anomaly_${level}`, chip: chipForAnomalyLevel(level, true), count: countText(n), group: 'pins' })
      }
    }
  }
  const c = isObject(sites) && sites.state === 'ready' && isObject(sites.counts) ? sites.counts : null
  if (c) {
    chips.push({ id: 'sites_measured', chip: chipForStatus(STATUS.MEASURED), count: countText(c.measured), group: 'sites' })
    if (c.noUsable > 0) chips.push({ id: 'sites_no_usable', chip: chipForStatus(STATUS.NO_USABLE_DATA), count: countText(c.noUsable), group: 'sites' })
    if (c.notChecked > 0) chips.push({ id: 'sites_not_checked', chip: chipForStatus(STATUS.NOT_CHECKED_YET), count: countText(c.notChecked), group: 'sites' })
    if (c.stale > 0) chips.push({ id: 'sites_stale', chip: chipForStatus(STATUS.STALE), count: countText(c.stale), group: 'sites' })
  }
  return chips
}

/**
 * The left card's headline and sub-line, as i18n messages.
 *   headline: sites with an index reading ("6 of 7 stations have an index
 *   reading"), or the loading / error / empty wording;
 *   subline: the pins of the scan shown ("5 highest-NDCI pins in this
 *   scan" / "3 anomaly pins (TEST) in this scan"), or null.
 */
export function buildMapHeadline(input) {
  const { sites, pins } = isObject(input) ? input : {}
  let headline
  if (!isObject(sites) || sites.state === 'loading') headline = msg('glass.list.headline_loading')
  else if (sites.state === 'error') headline = msg('glass.list.headline_error')
  else if (sites.state === 'empty') headline = msg('glass.list.headline_empty')
  else {
    const c = sites.counts
    headline = c.measured === 0
      ? msg('glass.list.headline_none', { total: countText(c.total) })
      : msg('glass.list.headline_sites', { n: countText(c.measured), total: countText(c.total) })
  }
  let subline = null
  if (isObject(pins) && pins.state === 'ready') {
    const n = countText(pins.items.length)
    subline = pins.mode === 'anomaly' ? msg('glass.list.subline_anomaly', { n }) : msg('glass.list.subline_ndci', { n })
  } else if (isObject(pins) && pins.state === 'empty') {
    subline = msg('glass.list.subline_none')
  }
  return { headline, subline }
}

/**
 * The top bar's freshness chip, from `/raster-scan` `poll` (the same
 * classification as the Overview banner) and `latest_scene`.
 * @returns {{state, tone: 'ok'|'attention'|'neutral', short, detail, scene}}
 *   `short` is the chip text, `detail` the Overview's poll line (same
 *   wording), `scene` the Overview's latest-scene line (or null).
 */
export function buildUpdateChip(input) {
  const { raster, request, now } = isObject(input) ? input : {}
  const req = isObject(request) ? { loading: request.loading === true, error: request.error ?? null } : { loading: false, error: null }
  const nowMs = finite(now) ? now : Date.now()
  const block = pollBlock(raster ?? null, req, nowMs)
  if (block.state === 'loading') {
    return { state: 'loading', tone: 'neutral', short: msg('glass.updated.loading'), detail: block.line, scene: null }
  }
  if (block.state === 'error') {
    return { state: 'error', tone: 'attention', short: msg('glass.updated.error'), detail: block.line, scene: null }
  }
  const health = classifyPoll(isObject(raster) ? raster.poll : null, nowMs)
  const sceneBlock = latestSceneBlock(raster, req, null)
  const scene = sceneBlock.state === 'ready' || sceneBlock.state === 'empty' ? sceneBlock.line : null
  const age = ageMessage(health.ageMs)
  let short
  if (health.state === 'ok') short = msg('glass.updated.ok', { age })
  else if (health.state === 'old') short = msg('glass.updated.old', { age })
  else if (health.state === 'failing') short = msg('glass.updated.failing')
  else short = msg('glass.updated.never')
  return { state: health.state, tone: health.state === 'ok' ? 'ok' : 'attention', short, detail: block.line, scene }
}
