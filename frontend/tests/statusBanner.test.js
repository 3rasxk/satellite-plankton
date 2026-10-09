/**
 * deriveBanner: the Overview headline, derived only from API fields.
 *
 * The danger it guards against is stale data presented as current: a
 * failed newer scan, a poll that could not check for newer scenes, or a
 * newest scene rejected for cloud must each be said out loud, in a fixed
 * precedence, before the routine "index readings are available" line.
 * A failing or old poll means newer scenes MAY exist unchecked -- never
 * "no newer scene".
 *
 * Fixtures are trimmed from the live API (BASELINE_MODE=test, run 6).
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { deriveBanner, BANNER_KEYS, POLL_MAX_AGE_HOURS } from '../src/lib/statusBanner.js'
import { createT, missingKeys } from '../src/i18n/index.js'

const NBSP = ' '
const NOW = Date.parse('2026-10-09T18:00:00Z')

function deepFreeze(o) {
  if (o && typeof o === 'object') {
    Object.values(o).forEach(deepFreeze)
    Object.freeze(o)
  }
  return o
}

const TEST_BASELINE = deepFreeze({
  mode: 'test', valid: true, kind: 'test', version: 'TEST-20261009-9fc9a022', reason: null,
})

const POLL_OK = deepFreeze({
  last_poll_started_at: '2026-10-09T17:03:12.049044+00:00',
  last_poll_ok_at: '2026-10-09T17:03:12.049044+00:00',
  last_error: null, last_error_at: null, last_error_kind: null,
})

const SCENE_USED = deepFreeze({
  acquisition_date: '2026-10-07', decision: 'passed', cloud_fraction: 0.40571297411298207,
  threshold_cloud_fraction: 0.5, min_water_pixels: 1000, reason: null, used_in_run_id: 6,
  assessed_at: '2026-10-09T13:04:47.527276+00:00', settled: true, used_in_served_run: true,
  reassessed_after_use: false,
})

const RASTER = deepFreeze({
  run_id: 6, status: 'ok', date_used: '2026-10-09', scale_m: 200, cell_count: 235290,
  scene_count: 32, oldest_scene_date: '2026-09-29', newest_scene_date: '2026-10-07',
  stale_run_id: null, reason: null, latest_scene: SCENE_USED,
  last_used_scene_date: '2026-10-07', poll: POLL_OK,
})

const SUMMARY = deepFreeze({
  total_sites: 7,
  risk_level_counts: {
    normal: 0, elevated: 0, watch: 0, warning: 0,
    not_evaluated: 6, not_checked_yet: 0, no_usable_data: 1,
  },
  stale_site_count: 0,
  baseline: null,
})

const raster = (patch) => deepFreeze({ ...RASTER, ...patch })
const summary = (counts, extra = {}) => deepFreeze({
  ...SUMMARY, ...extra, risk_level_counts: { ...SUMMARY.risk_level_counts, ...counts },
})
const derive = (args) => deriveBanner({ now: NOW, ...args })
const lineKeys = (b) => b.lines.map((l) => l.key)

test('healthy state: index readings for n of N sites, risk not evaluated, no extra lines', () => {
  const b = derive({ raster: RASTER, summary: SUMMARY, baseline: null })
  assert.equal(b.key, 'banner.indices_available')
  assert.deepEqual(b.params, { n: '6', total: '7' })
  assert.equal(b.tone, 'neutral')
  assert.deepEqual(b.lines, [])
})

test('no raster response at all: unknown, not "nothing measured"', () => {
  const b = derive({ raster: null, summary: SUMMARY })
  assert.equal(b.key, 'banner.raster_unknown')
  assert.equal(b.tone, 'attention')
  assert.deepEqual(lineKeys(b), ['banner.indices_available'])
})

test('run_id null: no raster yet; poll still reported; scene lines and stale run skipped', () => {
  const b = derive({
    raster: raster({ run_id: null, stale_run_id: 3, poll: null, newest_scene_date: null,
      latest_scene: { ...SCENE_USED, acquisition_date: '2026-10-08', decision: 'rejected_cloud', used_in_run_id: null } }),
    summary: SUMMARY,
  })
  assert.equal(b.key, 'banner.no_raster')
  assert.deepEqual(lineKeys(b), ['banner.poll_never', 'banner.indices_available'])
})

test('stale run: the last good raster is shown with its date and the failed run named', () => {
  const b = derive({ raster: raster({ stale_run_id: 7 }), summary: SUMMARY })
  assert.equal(b.key, 'banner.stale_run')
  assert.deepEqual(b.params, { run: '6', stale_run: '7', date: '2026-10-09' })
  assert.equal(b.tone, 'attention')
  assert.deepEqual(lineKeys(b), ['banner.indices_available'])
})

test('poll never completed: newer scenes may exist unchecked', () => {
  for (const poll of [null, { ...POLL_OK, last_poll_ok_at: null }]) {
    const b = derive({ raster: raster({ poll }), summary: SUMMARY })
    assert.equal(b.key, 'banner.poll_never')
    assert.equal(b.tone, 'attention')
  }
})

test('poll failing: an error newer than the last success', () => {
  const b = derive({
    raster: raster({ poll: { ...POLL_OK, last_error: 'auth expired', last_error_at: '2026-10-09T17:30:00+00:00', last_error_kind: 'gee_auth' } }),
    summary: SUMMARY,
  })
  assert.equal(b.key, 'banner.poll_failing')
  assert.deepEqual(b.params, { kind: 'gee_auth', last_ok: '2026-10-09 17:03Z' })

  const never = derive({
    raster: raster({ poll: { last_poll_ok_at: null, last_error: 'x', last_error_at: '2026-10-09T17:30:00Z', last_error_kind: null } }),
    summary: SUMMARY,
  })
  assert.equal(never.key, 'banner.poll_failing')
  assert.deepEqual(never.params, { kind: '—', last_ok: '—' })

  // An error with no timestamp cannot be shown to be older than the success.
  const undated = derive({
    raster: raster({ poll: { ...POLL_OK, last_error: 'x', last_error_at: null, last_error_kind: 'unexpected' } }),
    summary: SUMMARY,
  })
  assert.equal(undated.key, 'banner.poll_failing')
})

test('an old error followed by a later success is not a failing poll', () => {
  const b = derive({
    raster: raster({ poll: { ...POLL_OK, last_error: 'old', last_error_at: '2026-10-09T12:00:00Z', last_error_kind: 'gee_config' } }),
    summary: SUMMARY,
  })
  assert.equal(b.key, 'banner.indices_available')
})

test(`poll older than ${POLL_MAX_AGE_HOURS} h: newer scenes may exist unchecked`, () => {
  assert.equal(POLL_MAX_AGE_HOURS, 3)
  const old = derive({ raster: raster({ poll: { ...POLL_OK, last_poll_ok_at: '2026-10-09T12:59:00Z' } }), summary: SUMMARY })
  assert.equal(old.key, 'banner.poll_old')
  assert.deepEqual(old.params, { hours: '5', last_ok: '2026-10-09 12:59Z' })
  const edge = derive({ raster: raster({ poll: { ...POLL_OK, last_poll_ok_at: '2026-10-09T15:00:00Z' } }), summary: SUMMARY })
  assert.equal(edge.key, 'banner.indices_available')
})

test('newest scene rejected for cloud and newer than the last used date', () => {
  const b = derive({
    raster: raster({ latest_scene: { ...SCENE_USED, acquisition_date: '2026-10-08', decision: 'rejected_cloud', cloud_fraction: 0.83, used_in_run_id: null, used_in_served_run: false } }),
    summary: SUMMARY,
  })
  assert.equal(b.key, 'banner.scene_rejected_cloud')
  assert.deepEqual(b.params, { date: '2026-10-08', cloud: `83${NBSP}%`, threshold: `50${NBSP}%`, shown: '2026-10-07' })
  assert.equal(b.tone, 'attention')

  const noLastUsed = derive({
    raster: raster({ last_used_scene_date: null, latest_scene: { ...SCENE_USED, decision: 'rejected_cloud', used_in_run_id: null } }),
    summary: SUMMARY,
  })
  assert.equal(noLastUsed.key, 'banner.scene_rejected_cloud')
})

test('a rejected date that is not newer than the last used one raises nothing', () => {
  const b = derive({
    raster: raster({ latest_scene: { ...SCENE_USED, decision: 'rejected_cloud', reassessed_after_use: true } }),
    summary: SUMMARY,
  })
  assert.equal(b.key, 'banner.indices_available')
})

test('a newer scene rejected for another reason names the decision', () => {
  const b = derive({
    raster: raster({ latest_scene: { ...SCENE_USED, acquisition_date: '2026-10-08', decision: 'rejected_no_water', cloud_fraction: null, used_in_run_id: null } }),
    summary: SUMMARY,
  })
  assert.equal(b.key, 'banner.scene_not_used')
  assert.deepEqual(b.params, { date: '2026-10-08', decision: 'rejected_no_water', shown: '2026-10-07' })
})

test('a newer passing scene not yet in the served raster is said to be pending', () => {
  const b = derive({
    raster: raster({ latest_scene: { ...SCENE_USED, acquisition_date: '2026-10-08', used_in_run_id: null, used_in_served_run: false } }),
    summary: SUMMARY,
  })
  assert.equal(b.key, 'banner.scene_pending')
  assert.deepEqual(b.params, { date: '2026-10-08', shown: '2026-10-07' })
})

test('no site with a reading: unusable and not-checked counts stay separate', () => {
  const b = derive({ raster: RASTER, summary: summary({ not_evaluated: 0, no_usable_data: 3, not_checked_yet: 4 }) })
  assert.equal(b.key, 'banner.no_site_readings')
  assert.deepEqual(b.params, { no_usable: '3', not_checked: '4', total: '7' })
})

test('summary unavailable: the raster readings line is the fallback', () => {
  const b = derive({ raster: RASTER, summary: null })
  assert.equal(b.key, 'banner.raster_readings')
  assert.deepEqual(b.params, { date: '2026-10-07' })
})

test('precedence: stale run > poll > rejected scene > site readings, the rest as lines', () => {
  const bad = {
    stale_run_id: 7,
    poll: { ...POLL_OK, last_error: 'x', last_error_at: '2026-10-09T17:30:00Z', last_error_kind: 'gee_auth' },
    latest_scene: { ...SCENE_USED, acquisition_date: '2026-10-08', decision: 'rejected_cloud', cloud_fraction: 0.9, used_in_run_id: null },
  }
  const all = derive({ raster: raster(bad), summary: SUMMARY })
  assert.equal(all.key, 'banner.stale_run')
  assert.deepEqual(lineKeys(all), ['banner.poll_failing', 'banner.scene_rejected_cloud', 'banner.indices_available'])

  const noStale = derive({ raster: raster({ ...bad, stale_run_id: null }), summary: SUMMARY })
  assert.equal(noStale.key, 'banner.poll_failing')
  assert.deepEqual(lineKeys(noStale), ['banner.scene_rejected_cloud', 'banner.indices_available'])

  const pollOk = derive({ raster: raster({ ...bad, stale_run_id: null, poll: POLL_OK }), summary: SUMMARY })
  assert.equal(pollOk.key, 'banner.scene_rejected_cloud')
  assert.deepEqual(lineKeys(pollOk), ['banner.indices_available'])

  const noRaster = derive({ raster: raster({ ...bad, run_id: null }), summary: SUMMARY })
  assert.equal(noRaster.key, 'banner.no_raster')
  assert.deepEqual(lineKeys(noRaster), ['banner.poll_failing', 'banner.indices_available'])
})

test('TEST baseline active: the §5 banner line and the version are appended', () => {
  const b = derive({ raster: RASTER, summary: SUMMARY, baseline: TEST_BASELINE })
  assert.equal(b.key, 'banner.indices_available')
  assert.deepEqual(b.lines, [
    { key: 'truth.test_banner', params: {}, tone: 'attention' },
    { key: 'banner.test_baseline_version', params: { version: 'TEST-20261009-9fc9a022' }, tone: 'neutral' },
  ])
  // The useBaseline() shape works too, and so does summary.baseline as a fallback.
  const hook = derive({ raster: RASTER, summary: SUMMARY, baseline: { mode: 'test', valid: true, isTest: true, version: 'V1' } })
  assert.deepEqual(lineKeys(hook), ['truth.test_banner', 'banner.test_baseline_version'])
  const fromSummary = derive({ raster: RASTER, summary: summary({}, { baseline: TEST_BASELINE }) })
  assert.deepEqual(lineKeys(fromSummary), ['truth.test_banner', 'banner.test_baseline_version'])
})

test('TEST mode with an invalid baseline says so with the reason; mode off adds nothing', () => {
  const invalid = derive({ raster: RASTER, summary: SUMMARY, baseline: { mode: 'test', valid: false, kind: 'test', reason: 'signature_mismatch' } })
  assert.deepEqual(invalid.lines, [
    { key: 'banner.test_baseline_invalid', params: { reason: 'signature_mismatch' }, tone: 'neutral' },
  ])
  const off = derive({ raster: RASTER, summary: SUMMARY, baseline: { mode: 'off', valid: null } })
  assert.deepEqual(off.lines, [])
})

test('every key deriveBanner can return is listed and translated in both languages', () => {
  missingKeys.clear()
  const tTh = createT('th')
  const tEn = createT('en')
  for (const key of BANNER_KEYS) {
    assert.notEqual(tTh(key), key, `th ${key}`)
    assert.notEqual(tEn(key), key, `en ${key}`)
  }
  assert.equal(missingKeys.size, 0)
})

test('poll texts say newer scenes may exist unchecked, never that none exist', () => {
  for (const lang of ['th', 'en']) {
    const t = createT(lang)
    for (const key of ['banner.poll_never', 'banner.poll_failing', 'banner.poll_old']) {
      const text = t(key, { kind: 'gee_auth', last_ok: '2026-10-09 17:03Z', hours: '5' })
      if (lang === 'en') {
        assert.match(text, /newer scenes may exist that were not checked/, text)
        assert.doesNotMatch(text, /no newer scene/i, text)
      } else {
        assert.match(text, /อาจมีภาพ.*ที่ยังไม่ได้ตรวจสอบ/, text)
      }
    }
  }
})

test('risk tiers in the counts (gate active, future) are said not to be shown, never as "not evaluated"', () => {
  const b = derive({ raster: RASTER, summary: summary({ watch: 2, not_evaluated: 4 }) })
  assert.equal(b.key, 'banner.tiers_not_shown')
  assert.deepEqual(b.params, { tiers: '2', total: '7' })
  assert.equal(b.tone, 'attention')
  assert.ok(!lineKeys(b).includes('banner.indices_available'))
})

test('every derived key is listed, and its params fill every placeholder in both languages', () => {
  const cases = [
    { raster: RASTER, summary: SUMMARY, baseline: TEST_BASELINE },
    { raster: null, summary: null },
    { raster: null, summary: SUMMARY },
    { raster: raster({ run_id: null, poll: null }), summary: SUMMARY },
    { raster: raster({ stale_run_id: 7 }), summary: summary({ not_evaluated: 0, no_usable_data: 3, not_checked_yet: 4 }) },
    { raster: raster({ poll: { ...POLL_OK, last_error: 'x', last_error_at: '2026-10-09T17:30:00Z', last_error_kind: 'gee_auth' } }), summary: null },
    { raster: raster({ poll: { ...POLL_OK, last_poll_ok_at: '2026-10-09T01:00:00Z' } }), summary: summary({ watch: 1 }) },
    { raster: raster({ latest_scene: { ...SCENE_USED, acquisition_date: '2026-10-08', decision: 'rejected_cloud', cloud_fraction: 0.83, used_in_run_id: null } }), summary: SUMMARY },
    { raster: raster({ latest_scene: { ...SCENE_USED, acquisition_date: '2026-10-08', decision: 'rejected_no_water', used_in_run_id: null } }), summary: SUMMARY },
    { raster: raster({ latest_scene: { ...SCENE_USED, acquisition_date: '2026-10-08', used_in_served_run: false } }), summary: SUMMARY },
    { raster: RASTER, summary: SUMMARY, baseline: { mode: 'test', valid: false, kind: 'test', reason: 'signature_mismatch' } },
  ]
  const seen = new Set()
  missingKeys.clear()
  for (const args of cases) {
    const b = derive(args)
    for (const m of [b, ...b.lines]) {
      seen.add(m.key)
      assert.ok(BANNER_KEYS.includes(m.key), `${m.key} not in BANNER_KEYS`)
      for (const v of Object.values(m.params)) assert.equal(typeof v, 'string', `${m.key} param ${v}`)
      for (const lang of ['th', 'en']) {
        const text = createT(lang)(m.key, m.params)
        assert.doesNotMatch(text, /\{\w+\}/, `${lang} ${m.key} left a placeholder: ${text}`)
      }
    }
  }
  assert.equal(missingKeys.size, 0)
  // The fixtures above reach every key the module can return.
  assert.deepEqual([...BANNER_KEYS].filter((k) => !seen.has(k)), [])
})
