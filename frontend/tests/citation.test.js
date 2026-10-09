/**
 * buildCitation: a plain-text citation that names exactly what was seen
 * (app version and commit, raster run, scene dates, TEST baseline version
 * when one is in force, access date, permalink) and claims nothing else.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { buildCitation, APP_NAME } from '../src/lib/citation.js'
import { appVersion, gitSha } from '../src/lib/buildInfo.js'

const BASE = Object.freeze({
  version: '0.0.0',
  sha: '26ed29c',
  runId: 6,
  oldestScene: '2026-09-29',
  newestScene: '2026-10-07',
  accessedAt: '2026-10-10T08:15:00Z',
  permalink: 'http://localhost:5173/map?lat=13&lng=100.6&run=6&layer=ndci',
})

test('the app is cited by its own name', () => {
  assert.equal(APP_NAME, 'Plankton Watch')
})

test('English citation snapshot', () => {
  assert.equal(
    buildCitation({ ...BASE, lang: 'en' }),
    'Plankton Watch (v0.0.0, 26ed29c), raster run 6, scenes 2026-09-29–2026-10-07, '
      + 'accessed 2026-10-10. http://localhost:5173/map?lat=13&lng=100.6&run=6&layer=ndci',
  )
})

test('Thai citation snapshot', () => {
  assert.equal(
    buildCitation({ ...BASE, lang: 'th' }),
    'Plankton Watch (v0.0.0, 26ed29c), รอบสแกนแรสเตอร์ 6, ภาพถ่ายดาวเทียมวันที่ 2026-09-29–2026-10-07, '
      + 'สืบค้นเมื่อ 2026-10-10. http://localhost:5173/map?lat=13&lng=100.6&run=6&layer=ndci',
  )
})

test('the TEST baseline version is included when present, in both languages', () => {
  const en = buildCitation({ ...BASE, lang: 'en', baselineVersion: 'TEST-20261009-9fc9a022' })
  assert.equal(
    en,
    'Plankton Watch (v0.0.0, 26ed29c), raster run 6, scenes 2026-09-29–2026-10-07, '
      + 'TEST baseline TEST-20261009-9fc9a022, accessed 2026-10-10. '
      + 'http://localhost:5173/map?lat=13&lng=100.6&run=6&layer=ndci',
  )
  const th = buildCitation({ ...BASE, lang: 'th', baselineVersion: 'TEST-20261009-9fc9a022' })
  assert.match(th, /บรรทัดฐานทดสอบ \(TEST\) TEST-20261009-9fc9a022, สืบค้นเมื่อ 2026-10-10\./)
})

test('unknowns are "—", a single scene date is not repeated, no permalink ends at the full stop', () => {
  assert.equal(
    buildCitation({ lang: 'en', version: 'dev', sha: 'dev', runId: null, oldestScene: null, newestScene: null, accessedAt: null }),
    'Plankton Watch (dev, dev), raster run —, scenes —, accessed —.',
  )
  assert.match(
    buildCitation({ ...BASE, lang: 'en', oldestScene: '2026-10-07', permalink: null }),
    /scenes 2026-10-07, accessed 2026-10-10\.$/,
  )
  assert.match(buildCitation({ ...BASE, lang: 'en', accessedAt: new Date(Date.UTC(2026, 9, 11, 23, 59)) }),
    /accessed 2026-10-11\./)
  assert.match(buildCitation({ ...BASE, lang: 'fr' }), /รอบสแกนแรสเตอร์/, 'unsupported language falls back to Thai')
})

test('a citation makes no claim beyond provenance', () => {
  for (const lang of ['th', 'en']) {
    const text = buildCitation({ ...BASE, lang, baselineVersion: 'TEST-X' })
    assert.doesNotMatch(text, /bloom|risk|บลูม|เสี่ยง|normal|ปกติ/i, text)
  }
})

test('build info falls back to "dev" outside a Vite build', () => {
  assert.equal(typeof appVersion, 'string')
  assert.equal(typeof gitSha, 'string')
  assert.equal(appVersion, 'dev')
  assert.equal(gitSha, 'dev')
})
