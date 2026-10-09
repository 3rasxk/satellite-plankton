/**
 * The two dictionaries and the translation function every page goes through.
 *
 * Parity is the point: a key that exists in Thai but not in English (or a
 * `{param}` one side forgot) renders as a raw key or an unfilled brace in
 * one language only, which nobody notices until a judge toggles the
 * language. The wording checks defend the truth boundary at the source:
 * no string may present a risk level (other than to deny one) or claim a
 * bloom is present or absent.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import th from '../src/i18n/th.js'
import en from '../src/i18n/en.js'
import {
  SUPPORTED, DEFAULT_LANG, STORAGE_KEY, detectLang, createT, missingKeys,
} from '../src/i18n/index.js'
import { STATUS, ANOMALY_CHIP_KEYS } from '../src/lib/statusChip.js'
import { BANNER_KEYS } from '../src/lib/statusBanner.js'
import { NULL_REASONS } from '../src/lib/format.js'

function flatten(obj, prefix = '', out = new Map()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v !== null && typeof v === 'object') flatten(v, key, out)
    else out.set(key, v)
  }
  return out
}

const TH = flatten(th)
const EN = flatten(en)
const placeholders = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()

test('SUPPORTED languages are Thai and English, Thai first and default', () => {
  assert.deepEqual([...SUPPORTED], ['th', 'en'])
  assert.equal(DEFAULT_LANG, 'th')
  assert.equal(STORAGE_KEY, 'plankton.lang')
})

test('TH and EN have identical deep key sets', () => {
  const onlyTh = [...TH.keys()].filter((k) => !EN.has(k))
  const onlyEn = [...EN.keys()].filter((k) => !TH.has(k))
  assert.deepEqual(onlyTh, [], `keys only in th.js: ${onlyTh.join(', ')}`)
  assert.deepEqual(onlyEn, [], `keys only in en.js: ${onlyEn.join(', ')}`)
  assert.ok(TH.size > 50, 'the foundation dictionaries are populated')
})

test('every leaf is a non-empty string in both languages', () => {
  for (const [name, dict] of [['th', TH], ['en', EN]]) {
    for (const [key, value] of dict) {
      assert.equal(typeof value, 'string', `${name}:${key} is not a string`)
      assert.ok(value.trim().length > 0, `${name}:${key} is empty`)
    }
  }
})

test('each key uses the same {param} placeholders in both languages', () => {
  for (const [key, value] of TH) {
    assert.deepEqual(placeholders(value), placeholders(EN.get(key)), `placeholder drift at ${key}`)
  }
})

test('every status chip, banner key and null reason has text in both languages', () => {
  const needed = [
    ...Object.values(STATUS).map((k) => `status.${k}`),
    ...ANOMALY_CHIP_KEYS.map((k) => `status.${k}`),
    ...BANNER_KEYS,
    ...NULL_REASONS.map((r) => `reason.${r}`),
  ]
  for (const key of needed) {
    assert.ok(TH.has(key), `th.js lacks ${key}`)
    assert.ok(EN.has(key), `en.js lacks ${key}`)
  }
})

test('the nav lists the five routes in both languages', () => {
  for (const route of ['overview', 'map', 'sites', 'methods', 'data']) {
    assert.ok(TH.has(`nav.${route}`) && EN.has(`nav.${route}`), `nav.${route}`)
  }
  assert.equal(EN.get('nav.data'), 'Data & limits')
  assert.equal(TH.get('nav.overview'), 'ภาพรวม')
})

test('the TEST banner is the test-baseline spec §5 wording', () => {
  assert.equal(
    TH.get('truth.test_banner'),
    'บรรทัดฐานทดสอบ (TEST): ค่าผิดปกติเทียบกับประวัติของตำแหน่งเดียวกัน ยังไม่สอบเทียบกับเหตุการณ์จริง ไม่ใช่การประเมินความเสี่ยงบลูม',
  )
  assert.match(EN.get('truth.test_banner'), /^TEST baseline: /)
  assert.match(EN.get('truth.test_banner'), /own history/)
  assert.match(EN.get('truth.test_banner'), /not .*calibrated/)
  assert.match(EN.get('truth.test_banner'), /not a bloom-risk assessment/)
})

test('the truth-boundary footer carries the three binding points in both languages', () => {
  for (const dict of [TH, EN]) {
    for (const key of ['truth.point_1', 'truth.point_2', 'truth.point_3', 'truth.point_3_test']) {
      assert.ok(dict.has(key), key)
    }
  }
  assert.match(EN.get('truth.point_1'), /satellite pixel resolution/)
  assert.match(EN.get('truth.point_1'), /never organisms/)
  assert.equal(EN.get('truth.point_2'), 'Small or dispersed blooms may be missed.')
  assert.match(EN.get('truth.point_3'), /^Detection and prediction are separate claims\./)
  assert.match(EN.get('truth.point_3'), /no risk level/)
  assert.match(EN.get('truth.point_3_test'), /TEST/)
  assert.match(EN.get('truth.point_3_test'), /no risk level/)
  // The Level-3 MODIS grid is ~4.6 km (/methods); the footer must not repeat
  // the old "~1 km" figure as the product resolution.
  assert.doesNotMatch(EN.get('truth.point_1'), /1\s*km/)
  assert.doesNotMatch(TH.get('truth.point_1'), /1\s*(km|กม|กิโลเมตร)/)
})

test('risk wording appears only negated; bloom wording only negated or hedged', () => {
  const NEGATION = /\b(not|no|never|neither|nor|cannot)\b|ไม่/i
  const HEDGE = /\b(may|might)\b|อาจ/i
  for (const [name, dict] of [['th', TH], ['en', EN]]) {
    for (const [key, value] of dict) {
      if (/risk|เสี่ยง/i.test(value)) {
        assert.match(value, NEGATION, `${name}:${key} mentions risk without negating it: ${value}`)
      }
      if (/bloom|บลูม/i.test(value)) {
        assert.ok(NEGATION.test(value) || HEDGE.test(value),
          `${name}:${key} mentions a bloom without negation or hedge: ${value}`)
      }
      assert.doesNotMatch(value, /\b(bloom detected|bloom present|bloom-free|all clear|safe water)\b/i,
        `${name}:${key}`)
      assert.doesNotMatch(value, /ปลอดภัย|ตรวจพบบลูมแล้ว/, `${name}:${key}`)
    }
  }
})

test('detectLang: ?lang= wins over storage, storage over the Thai default', () => {
  const storage = { getItem: (k) => (k === 'plankton.lang' ? 'en' : null) }
  assert.equal(detectLang({ search: '?lang=th', storage }), 'th')
  assert.equal(detectLang({ search: '?lang=en', storage: { getItem: () => 'th' } }), 'en')
  assert.equal(detectLang({ search: '', storage }), 'en')
  assert.equal(detectLang({ search: '?x=1', storage: { getItem: () => null } }), 'th')
  assert.equal(detectLang({}), 'th')
  assert.equal(detectLang(), 'th')
  assert.equal(detectLang({ search: new URLSearchParams('lang=EN') }), 'en')
  assert.equal(detectLang({ search: 'lang=en' }), 'en')
})

test('detectLang: the browser language never overrides the Thai default', () => {
  assert.equal(detectLang({ navigatorLang: 'en-US' }), 'th')
  assert.equal(detectLang({ navigatorLang: 'en', storage: { getItem: () => null } }), 'th')
})

test('detectLang: invalid values are ignored and a throwing storage is survived', () => {
  const throwing = { getItem() { throw new Error('SecurityError: storage blocked') } }
  assert.equal(detectLang({ storage: throwing }), 'th')
  assert.equal(detectLang({ search: '?lang=en', storage: throwing }), 'en')
  assert.equal(detectLang({ search: '?lang=fr', storage: { getItem: () => 'de' } }), 'th')
  assert.equal(detectLang({ search: '?lang=fr', storage: { getItem: () => 'en' } }), 'en')
  assert.equal(detectLang({ storage: {} }), 'th')
})

test('createT interpolates {name} params', () => {
  const tEn = createT('en')
  const tTh = createT('th')
  assert.equal(tEn('common.of', { n: 6, total: 7 }), '6 of 7')
  assert.equal(tTh('common.of', { n: 6, total: 7 }), '6 จาก 7')
  // An unknown value renders as the null mark, never as "null" or "0".
  assert.equal(tEn('common.of', { n: null, total: 7 }), '— of 7')
  assert.equal(tEn('common.of', { n: Number.NaN, total: 7 }), '— of 7')
  // A real zero stays a zero.
  assert.equal(tEn('common.of', { n: 0, total: 7 }), '0 of 7')
  // A forgotten param stays visible rather than silently vanishing.
  assert.equal(tEn('common.of', { n: 1 }), '1 of {total}')
  assert.equal(tEn('common.of'), '{n} of {total}')
})

test('createT returns the key for a missing key, records it, and never throws', () => {
  missingKeys.clear()
  const t = createT('en')
  assert.equal(t('nope.not_a_key'), 'nope.not_a_key')
  assert.ok(missingKeys.has('nope.not_a_key'))
  // A namespace is not a string: treated as missing.
  assert.equal(t('status'), 'status')
  assert.ok(missingKeys.has('status'))
  assert.doesNotThrow(() => t(undefined))
  assert.doesNotThrow(() => t(null, null))
  assert.doesNotThrow(() => t('common.of', 'not-an-object'))
  assert.doesNotThrow(() => t('__proto__'))
  assert.equal(t('constructor'), 'constructor')
  missingKeys.clear()
})

test('createT falls back to Thai for an unsupported language', () => {
  assert.equal(createT('fr')('nav.overview'), th.nav.overview)
  assert.equal(createT(undefined)('nav.overview'), th.nav.overview)
  assert.equal(createT('EN')('nav.overview'), en.nav.overview)
  assert.equal(createT('en').lang, 'en')
  assert.equal(createT('xx').lang, 'th')
})

test('saveLang stores a supported code and survives a refusing storage', async () => {
  const { saveLang } = await import('../src/i18n/index.js')
  const store = new Map()
  const storage = { setItem: (k, v) => store.set(k, v) }
  assert.equal(saveLang(storage, 'EN'), true)
  assert.equal(store.get('plankton.lang'), 'en')
  assert.equal(saveLang(storage, 'fr'), false)
  assert.equal(saveLang({ setItem() { throw new Error('QuotaExceededError') } }, 'th'), false)
  assert.equal(saveLang(null, 'th'), false)
})
