/**
 * deriveBanner: the status headline (Overview, Map), derived only from API
 * fields -- dashboard spec §4.1, plus the latest-scene messages (test-baseline
 * spec §7) and the TEST-baseline line (§5).
 *
 * Data source:
 *   - `GET /raster-scan`: run_id, stale_run_id, date_used, newest_scene_date,
 *     latest_scene, last_used_scene_date, poll (RasterScanResponse);
 *   - `GET /summary`: total_sites, risk_level_counts, baseline (SummaryResponse);
 *   - the baseline block (`/summary`, `/risk-map`, or useBaseline()).
 *
 * Output: `{key, params, tone, lines}`. `key` is the headline's i18n key,
 * `params` its already-formatted text parameters, `tone` 'neutral' or
 * 'attention' (never a "safe" tone), and `lines` the remaining messages in
 * the same precedence order, each `{key, params, tone}`.
 *
 * Precedence (first match is the headline; the rest become lines):
 *   1. no raster response at all            banner.raster_unknown
 *      run_id null                          banner.no_raster
 *   2. stale_run_id set                     banner.stale_run
 *   3. poll failing / never / older than 3 h  banner.poll_failing|poll_never|poll_old
 *      (newer scenes MAY exist unchecked -- never "no newer scene")
 *   4. newest assessed scene newer than the last used one and not in the
 *      raster: rejected for cloud, rejected otherwise, or passed but pending
 *   5. monitoring-site readings             banner.indices_available |
 *      no_site_readings | raster_readings (summary unavailable) |
 *      tiers_not_shown (the API sent risk tiers this UI does not display)
 *   then, appended: the TEST-baseline lines.
 * With no raster run, the stale-run and scene messages are skipped (there is
 * no picture for them to qualify); the poll is still reported.
 *
 * Limitations: pure function of its inputs (pass `now` for tests). It never
 * claims a bloom is present or absent and never renders a risk tier.
 */
import { formatValue, toUtcMs, NULL_TEXT } from './format.js'

export const POLL_MAX_AGE_HOURS = 3

/** Every key deriveBanner can return, headline or line. */
export const BANNER_KEYS = Object.freeze([
  'banner.raster_unknown',
  'banner.no_raster',
  'banner.stale_run',
  'banner.poll_never',
  'banner.poll_failing',
  'banner.poll_old',
  'banner.scene_rejected_cloud',
  'banner.scene_not_used',
  'banner.scene_pending',
  'banner.indices_available',
  'banner.no_site_readings',
  'banner.raster_readings',
  'banner.tiers_not_shown',
  'truth.test_banner',
  'banner.test_baseline_version',
  'banner.test_baseline_invalid',
])

const HOUR_MS = 3600000
const TIER_COUNT_KEYS = ['normal', 'elevated', 'watch', 'warning']

const message = (key, params = {}, tone = 'neutral') => ({ key, params, tone })
const isObject = (v) => v !== null && typeof v === 'object'
const hasValue = (v) => v !== null && v !== undefined
// Ids and API codes, verbatim ("—" when absent). Not number-formatted: a run
// id is a label, so it is never grouped or rounded.
const plain = (v) => ((typeof v === 'number' && Number.isFinite(v)) || (typeof v === 'string' && v !== '')
  ? String(v) : NULL_TEXT)
const dateText = (v) => formatValue(v, { kind: 'date' }).text
const countText = (v) => formatValue(v, { kind: 'count' }).text
const utcText = (v) => formatValue(v, { kind: 'datetime-utc' }).text
const percentText = (v) => formatValue(v, { kind: 'percent', decimals: 0 }).text

function pollMessage(poll, nowMs) {
  if (!isObject(poll)) return message('banner.poll_never', {}, 'attention')
  const okMs = toUtcMs(poll.last_poll_ok_at)
  const errMs = toUtcMs(poll.last_error_at)
  // An error is current unless a success is shown to be later than it.
  if (hasValue(poll.last_error) && (okMs === null || errMs === null || errMs > okMs)) {
    return message('banner.poll_failing', {
      kind: plain(poll.last_error_kind),
      last_ok: utcText(poll.last_poll_ok_at),
    }, 'attention')
  }
  if (okMs === null) return message('banner.poll_never', {}, 'attention')
  const ageMs = nowMs - okMs
  if (ageMs > POLL_MAX_AGE_HOURS * HOUR_MS) {
    return message('banner.poll_old', {
      hours: String(Math.floor(ageMs / HOUR_MS)),
      last_ok: utcText(poll.last_poll_ok_at),
    }, 'attention')
  }
  return null
}

function sceneMessage(raster) {
  const scene = raster.latest_scene
  if (!isObject(scene) || typeof scene.acquisition_date !== 'string') return null
  const lastUsed = raster.last_used_scene_date
  // ISO dates compare correctly as strings. With no used date on record the
  // newest assessed date cannot be shown to be old, so it is reported.
  const newer = typeof lastUsed !== 'string' || scene.acquisition_date > lastUsed
  if (!newer) return null
  const shown = dateText(raster.newest_scene_date ?? lastUsed)
  const date = scene.acquisition_date
  if (scene.decision === 'passed') {
    if (scene.used_in_served_run === true) return null
    return message('banner.scene_pending', { date, shown }, 'attention')
  }
  if (scene.decision === 'rejected_cloud') {
    return message('banner.scene_rejected_cloud', {
      date,
      cloud: percentText(scene.cloud_fraction),
      threshold: percentText(scene.threshold_cloud_fraction),
      shown,
    }, 'attention')
  }
  return message('banner.scene_not_used', { date, decision: plain(scene.decision), shown }, 'attention')
}

function siteMessage(summary, raster) {
  const counts = isObject(summary) ? summary.risk_level_counts : null
  const total = isObject(summary) ? summary.total_sites : null
  if (!isObject(counts) || !Number.isFinite(total)) {
    if (isObject(raster) && hasValue(raster.run_id)) {
      return message('banner.raster_readings', { date: dateText(raster.newest_scene_date) }, 'neutral')
    }
    return null
  }
  const n = (k) => (Number.isFinite(counts[k]) ? counts[k] : 0)
  const tiers = TIER_COUNT_KEYS.reduce((sum, k) => sum + n(k), 0)
  if (tiers > 0) {
    // Gate-active (future): this dashboard has no code path that renders a
    // tier, so it says so instead of claiming risk is "not evaluated".
    return message('banner.tiers_not_shown', { tiers: countText(tiers), total: countText(total) }, 'attention')
  }
  if (n('not_evaluated') > 0) {
    return message('banner.indices_available', {
      n: countText(n('not_evaluated')), total: countText(total),
    }, 'neutral')
  }
  return message('banner.no_site_readings', {
    no_usable: countText(n('no_usable_data')),
    not_checked: countText(n('not_checked_yet')),
    total: countText(total),
  }, 'attention')
}

function baselineLines(baseline) {
  if (!isObject(baseline)) return []
  const active = baseline.isTest === true || (baseline.mode === 'test' && baseline.valid === true)
  if (active) {
    return [
      message('truth.test_banner', {}, 'attention'),
      message('banner.test_baseline_version', { version: plain(baseline.version) }, 'neutral'),
    ]
  }
  if (baseline.mode === 'test' && baseline.valid === false) {
    return [message('banner.test_baseline_invalid', { reason: plain(baseline.reason) }, 'neutral')]
  }
  return []
}

/**
 * @param {{raster?: object|null, summary?: object|null, baseline?: object|null, now?: number|Date}} input
 * @returns {{key: string, params: object, tone: 'neutral'|'attention', lines: Array<{key, params, tone}>}}
 */
export function deriveBanner(input) {
  const { raster, summary, baseline, now } = isObject(input) ? input : {}
  const nowMs = now instanceof Date ? now.getTime() : Number.isFinite(now) ? now : Date.now()

  const messages = []
  if (!isObject(raster)) {
    messages.push(message('banner.raster_unknown', {}, 'attention'))
  } else {
    const hasRun = hasValue(raster.run_id)
    if (!hasRun) {
      messages.push(message('banner.no_raster', {}, 'attention'))
    } else if (hasValue(raster.stale_run_id)) {
      messages.push(message('banner.stale_run', {
        run: plain(raster.run_id), stale_run: plain(raster.stale_run_id), date: dateText(raster.date_used),
      }, 'attention'))
    }
    const poll = pollMessage(raster.poll, nowMs)
    if (poll) messages.push(poll)
    if (hasRun) {
      const scene = sceneMessage(raster)
      if (scene) messages.push(scene)
    }
  }
  const sites = siteMessage(summary, raster)
  if (sites) messages.push(sites)

  const [head, ...rest] = messages
  const lines = [...rest, ...baselineLines(baseline ?? (isObject(summary) ? summary.baseline : null))]
  return { key: head.key, params: head.params, tone: head.tone, lines }
}
