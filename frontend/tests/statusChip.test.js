/**
 * The closed status vocabulary and the only functions allowed to map API
 * status strings onto it.
 *
 * Two failure modes matter: a status string the UI has never seen being
 * shown as "Measured" (an unknown must never read as a reading), and a
 * chip carrying colour semantics (risk colours are reserved and unused;
 * chips carry a tone, a hatch flag and an icon, and their words come from
 * the dictionaries).
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  STATUS, TONES, ANOMALY_CHIP_KEYS, SITE_STATUSES, PIXEL_STATES,
  chipForPixelState, chipForSite, chipForAnomalyLevel,
} from '../src/lib/statusChip.js'
import { createT, missingKeys } from '../src/i18n/index.js'

const keys = (chips) => chips.map((c) => c.key)

test('STATUS is exactly the seven-word closed vocabulary', () => {
  assert.deepEqual({ ...STATUS }, {
    MEASURED: 'measured',
    NOT_MEASURED: 'not_measured',
    OUTSIDE_STUDY_AREA: 'outside_study_area',
    NO_USABLE_DATA: 'no_usable_data',
    NOT_CHECKED_YET: 'not_checked_yet',
    NOT_EVALUATED: 'not_evaluated',
    STALE: 'stale',
  })
  assert.ok(Object.isFrozen(STATUS))
  assert.deepEqual([...TONES], ['neutral', 'attention', 'strong', 'muted'])
})

test('chipForPixelState maps the three drawn states; anything else is no usable data', () => {
  assert.deepEqual([...PIXEL_STATES], ['reading', 'not_measured', 'outside_study_area'])
  const table = {
    reading: 'measured',
    not_measured: 'not_measured',
    outside_study_area: 'outside_study_area',
    measured: 'no_usable_data',
    '': 'no_usable_data',
    toString: 'no_usable_data',
    __proto__x: 'no_usable_data',
  }
  for (const [state, expected] of Object.entries(table)) {
    assert.equal(chipForPixelState(state).key, expected, state)
  }
  assert.equal(chipForPixelState(undefined).key, 'no_usable_data')
  assert.equal(chipForPixelState(null).key, 'no_usable_data')
})

test('chipForSite: every API status string is mapped, unknown never reads as measured', () => {
  assert.deepEqual([...SITE_STATUSES],
    ['ok', 'no_imagery', 'no_water_pixels', 'no_climatology', 'error', 'no_data_yet'])
  const table = [
    [{ status: 'ok', risk_level: null, stale: false }, ['measured', 'not_evaluated']],
    [{ status: 'no_imagery', risk_level: null, stale: false }, ['no_usable_data']],
    [{ status: 'no_water_pixels', risk_level: null }, ['no_usable_data']],
    [{ status: 'no_climatology', risk_level: null }, ['no_usable_data']],
    [{ status: 'error', risk_level: null }, ['no_usable_data']],
    [{ status: 'no_data_yet', risk_level: null }, ['not_checked_yet']],
    [{ status: 'ok', risk_level: null, stale: true }, ['measured', 'not_evaluated', 'stale']],
    [{ status: 'error', risk_level: null, stale: true }, ['no_usable_data', 'stale']],
    [{ status: 'banana', risk_level: null }, ['no_usable_data']],
    [{ status: 'constructor' }, ['no_usable_data']],
    [{}, ['no_usable_data']],
  ]
  for (const [props, expected] of table) {
    assert.deepEqual(keys(chipForSite(props)), expected, JSON.stringify(props))
  }
  assert.deepEqual(keys(chipForSite(null)), ['no_usable_data'])
  assert.deepEqual(keys(chipForSite(undefined)), ['no_usable_data'])
  // A future, gate-active tier is not rendered here, and no "not evaluated"
  // note is added on top of it: this module has no tier chip at all.
  assert.deepEqual(keys(chipForSite({ status: 'ok', risk_level: 'watch' })), ['measured'])
  // Accepts a whole GeoJSON feature as well as its properties.
  assert.deepEqual(keys(chipForSite({ type: 'Feature', properties: { status: 'no_data_yet' } })),
    ['not_checked_yet'])
})

test('chipForAnomalyLevel: levels, TEST marker, tones and hatching', () => {
  const table = [
    ['normal', true, { key: 'anomaly_normal_test', tone: 'neutral', hatch: false }],
    ['watch', true, { key: 'anomaly_watch_test', tone: 'attention', hatch: true }],
    ['high', true, { key: 'anomaly_high_test', tone: 'strong', hatch: true }],
    [null, true, { key: 'anomaly_not_assessed_test', tone: 'muted', hatch: false }],
    ['normal', false, { key: 'anomaly_normal', tone: 'neutral', hatch: false }],
    ['watch', false, { key: 'anomaly_watch', tone: 'attention', hatch: true }],
    ['high', false, { key: 'anomaly_high', tone: 'strong', hatch: true }],
    [null, false, { key: 'anomaly_not_assessed', tone: 'muted', hatch: false }],
    // An unknown level is "not assessed", never "normal".
    ['warning', true, { key: 'anomaly_not_assessed_test', tone: 'muted', hatch: false }],
    [undefined, false, { key: 'anomaly_not_assessed', tone: 'muted', hatch: false }],
  ]
  for (const [level, isTest, expected] of table) {
    const chip = chipForAnomalyLevel(level, isTest)
    assert.equal(chip.key, expected.key, `${level}/${isTest}`)
    assert.equal(chip.tone, expected.tone, `${level}/${isTest}`)
    assert.equal(chip.hatch, expected.hatch, `${level}/${isTest}`)
  }
  assert.deepEqual([...ANOMALY_CHIP_KEYS].sort(), [
    'anomaly_high', 'anomaly_high_test', 'anomaly_normal', 'anomaly_normal_test',
    'anomaly_not_assessed', 'anomaly_not_assessed_test', 'anomaly_watch', 'anomaly_watch_test',
  ])
})

test('every chip is {key, tone, hatch, icon} with no colour or risk semantics', () => {
  const chips = [
    ...PIXEL_STATES.map(chipForPixelState),
    ...SITE_STATUSES.flatMap((s) => chipForSite({ status: s, stale: true, risk_level: null })),
    ...['normal', 'watch', 'high', null].flatMap((l) => [chipForAnomalyLevel(l, true), chipForAnomalyLevel(l, false)]),
  ]
  for (const chip of chips) {
    assert.deepEqual(Object.keys(chip).sort(), ['hatch', 'icon', 'key', 'tone'])
    assert.ok(TONES.includes(chip.tone), chip.tone)
    assert.equal(typeof chip.hatch, 'boolean')
    assert.equal(typeof chip.icon, 'string')
  }
  const text = JSON.stringify(chips)
  assert.doesNotMatch(text, /\b(red|green|amber|orange|yellow)\b|#[0-9a-f]{3}|--risk|risk/i)
})

test('chips are fresh objects: mutating one cannot change the vocabulary', () => {
  const a = chipForPixelState('reading')
  a.tone = 'strong'
  assert.equal(chipForPixelState('reading').tone, 'neutral')
})

test('every anomaly label carries (TEST) when isTest, in both languages', () => {
  missingKeys.clear()
  for (const lang of ['th', 'en']) {
    const t = createT(lang)
    for (const level of ['normal', 'watch', 'high', null]) {
      const label = t(`status.${chipForAnomalyLevel(level, true).key}`)
      assert.match(label, /\(TEST\)/, `${lang} ${level}: ${label}`)
      const plain = t(`status.${chipForAnomalyLevel(level, false).key}`)
      assert.doesNotMatch(plain, /TEST/, `${lang} ${level}: ${plain}`)
    }
  }
  assert.equal(missingKeys.size, 0, [...missingKeys].join(', '))
})
