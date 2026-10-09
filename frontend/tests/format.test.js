/**
 * formatValue: the one place a number becomes text.
 *
 * The rule it defends is the dashboard's first truth-boundary rule: an
 * unknown value is "—" with a reason, never "0" and never blank; and a
 * measured zero is "0.000", never "—". Everything else (minus sign,
 * decimals, ISO dates, UTC times) is house style the tests pin so a page
 * cannot drift from it.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { formatValue, MINUS, NULL_TEXT, NULL_REASONS } from '../src/lib/format.js'

const KINDS = ['index', 'fraction', 'percent', 'count', 'date', 'datetime-utc', 'coord', 'ms', 'mg-m3', 'z']
const NBSP = ' '

test('the null mark and the minus sign are the agreed characters', () => {
  assert.equal(NULL_TEXT, '—')
  assert.equal(MINUS, '−')
  assert.ok(NULL_REASONS.includes('not_available'))
  assert.ok(NULL_REASONS.includes('no_baseline'))
})

test('null, undefined, NaN and ±Infinity render — with a reason, for every kind', () => {
  for (const kind of KINDS) {
    for (const value of [null, undefined, Number.NaN, Infinity, -Infinity]) {
      const out = formatValue(value, { kind })
      assert.deepEqual(out, { text: '—', isNull: true, reason: 'not_available' }, `${kind} ${value}`)
    }
  }
})

test('a passed reason travels with the null', () => {
  assert.deepEqual(formatValue(null, { kind: 'index', reason: 'not_measured' }),
    { text: '—', isNull: true, reason: 'not_measured' })
  assert.deepEqual(formatValue(Number.NaN, { kind: 'z', reason: 'no_baseline' }),
    { text: '—', isNull: true, reason: 'no_baseline' })
})

test('an empty string is unknown, not zero; a non-numeric string is invalid', () => {
  assert.equal(formatValue('', { kind: 'index' }).text, '—')
  assert.equal(formatValue('   ', { kind: 'count' }).isNull, true)
  assert.deepEqual(formatValue('abc', { kind: 'index' }), { text: '—', isNull: true, reason: 'invalid_value' })
  assert.equal(formatValue(true, { kind: 'index' }).reason, 'invalid_value')
  assert.equal(formatValue('0.25', { kind: 'index' }).text, '0.250')
})

test('a real zero stays a zero', () => {
  assert.deepEqual(formatValue(0, { kind: 'index' }), { text: '0.000', isNull: false, reason: null })
  assert.equal(formatValue(0, { kind: 'count' }).text, '0')
  assert.equal(formatValue(0, { kind: 'percent' }).text, `0.0${NBSP}%`)
  assert.equal(formatValue(0, { kind: 'z' }).text, '0.00')
  assert.equal(formatValue(0, { kind: 'fraction' }).text, '0.00')
  assert.equal(formatValue(0, { kind: 'mg-m3' }).text, `0.00${NBSP}mg${NBSP}m⁻³`)
})

test('negatives use U+2212, and a value that rounds to zero is not shown as minus zero', () => {
  assert.equal(formatValue(-0.0123, { kind: 'index' }).text, '−0.012')
  assert.equal(formatValue(-2.5, { kind: 'z' }).text, '−2.50')
  assert.equal(formatValue(-12, { kind: 'count' }).text, '−12')
  assert.equal(formatValue(-0.0000001, { kind: 'index' }).text, '0.000')
  assert.equal(formatValue(-0, { kind: 'index' }).text, '0.000')
  assert.doesNotMatch(formatValue(-1.5, { kind: 'index' }).text, /-/)
})

test('index: three decimals by default; decimals override', () => {
  assert.equal(formatValue(0.1803278625011444, { kind: 'index' }).text, '0.180')
  assert.equal(formatValue(0.1803278625011444, { kind: 'index', decimals: 5 }).text, '0.18033')
  assert.equal(formatValue(1.440000057220459, { kind: 'index', decimals: 2 }).text, '1.44')
})

test('fraction and percent: percent takes a 0–1 fraction', () => {
  assert.equal(formatValue(0.40571297411298207, { kind: 'fraction' }).text, '0.41')
  assert.equal(formatValue(0.642290001011268, { kind: 'percent' }).text, `64.2${NBSP}%`)
  assert.equal(formatValue(0.5, { kind: 'percent', decimals: 0 }).text, `50${NBSP}%`)
  assert.equal(formatValue(1, { kind: 'percent' }).text, `100.0${NBSP}%`)
})

test('count: integers with thousands separators', () => {
  assert.equal(formatValue(235290, { kind: 'count' }).text, '235,290')
  assert.equal(formatValue(7, { kind: 'count' }).text, '7')
  assert.equal(formatValue(1234567, { kind: 'count' }).text, '1,234,567')
})

test('date: ISO YYYY-MM-DD in UTC from a date, a timestamp or epoch ms', () => {
  assert.equal(formatValue('2026-10-07', { kind: 'date' }).text, '2026-10-07')
  assert.equal(formatValue('2026-10-07T23:54:42.024000Z', { kind: 'date' }).text, '2026-10-07')
  assert.equal(formatValue('2026-10-08T03:00:00+07:00', { kind: 'date' }).text, '2026-10-07')
  assert.equal(formatValue(1791345282024, { kind: 'date' }).text, '2026-10-07')
  assert.equal(formatValue(new Date(Date.UTC(2026, 9, 10, 12)), { kind: 'date' }).text, '2026-10-10')
  assert.deepEqual(formatValue('2026-13-45', { kind: 'date' }), { text: '—', isNull: true, reason: 'invalid_value' })
  assert.equal(formatValue('yesterday', { kind: 'date' }).reason, 'invalid_value')
  assert.equal(formatValue(new Date('x'), { kind: 'date' }).reason, 'invalid_value')
})

test('datetime-utc: YYYY-MM-DD HH:MMZ, whatever offset the API used', () => {
  assert.equal(formatValue('2026-10-09T17:03:12.049044+00:00', { kind: 'datetime-utc' }).text, '2026-10-09 17:03Z')
  assert.equal(formatValue('2026-10-07T03:54:42.024000Z', { kind: 'datetime-utc' }).text, '2026-10-07 03:54Z')
  assert.equal(formatValue('2026-10-09T20:03:12+07:00', { kind: 'datetime-utc' }).text, '2026-10-09 13:03Z')
  // No offset: the API's timestamps are UTC, so a bare one is read as UTC,
  // never as the viewer's local time.
  assert.equal(formatValue('2026-10-09T13:05:04', { kind: 'datetime-utc' }).text, '2026-10-09 13:05Z')
  assert.equal(formatValue(1791345282024, { kind: 'datetime-utc' }).text, '2026-10-07 03:54Z')
  assert.equal(formatValue('2026-10-09', { kind: 'datetime-utc' }).text, '2026-10-09 00:00Z')
})

test('coord: five decimals by default; a degree unit attaches without a space', () => {
  assert.equal(formatValue(12.999520476493597, { kind: 'coord' }).text, '12.99952')
  assert.equal(formatValue(100.59963372269286, { kind: 'coord', unit: '°' }).text, '100.59963°')
  assert.equal(formatValue(-8.25, { kind: 'coord', decimals: 2 }).text, '−8.25')
})

test('ms: the exact integer, ungrouped, with its unit', () => {
  assert.equal(formatValue(1791345282024, { kind: 'ms' }).text, `1791345282024${NBSP}ms`)
  assert.equal(formatValue(0, { kind: 'ms' }).text, `0${NBSP}ms`)
})

test('mg-m3 and z', () => {
  assert.equal(formatValue(3.456, { kind: 'mg-m3' }).text, `3.46${NBSP}mg${NBSP}m⁻³`)
  assert.equal(formatValue(3.4452417189507827, { kind: 'z' }).text, '3.45')
  assert.equal(formatValue(26.18954647756971, { kind: 'z', decimals: 1 }).text, '26.2')
})

test('a unit is appended after a no-break space', () => {
  assert.equal(formatValue(200, { kind: 'count', unit: 'm' }).text, `200${NBSP}m`)
  assert.equal(formatValue(0.031, { kind: 'index', unit: 'DN' }).text, `0.031${NBSP}DN`)
})

test('formatValue never throws on odd input', () => {
  assert.doesNotThrow(() => formatValue({}, { kind: 'index' }))
  assert.doesNotThrow(() => formatValue([1], undefined))
  assert.doesNotThrow(() => formatValue(1, { kind: 'no-such-kind' }))
  assert.equal(formatValue(1, { kind: 'no-such-kind' }).isNull, false)
  assert.equal(formatValue({}, { kind: 'index' }).reason, 'invalid_value')
})

test('reasonKey maps known API codes (and their prefixed variants) to i18n keys, else null', async () => {
  const { reasonKey } = await import('../src/lib/format.js')
  assert.equal(reasonKey('zero_mad'), 'reason.zero_mad')
  assert.equal(reasonKey('baseline_invalid:signature_mismatch'), 'reason.baseline_invalid')
  assert.equal(reasonKey('something_new'), null)
  assert.equal(reasonKey(''), null)
  assert.equal(reasonKey(null), null)
})

test('toUtcMs reads offsets and treats a bare timestamp as UTC', async () => {
  const { toUtcMs } = await import('../src/lib/format.js')
  assert.equal(toUtcMs('2026-10-09T17:03:12.049044+00:00'), Date.UTC(2026, 9, 9, 17, 3, 12, 49))
  assert.equal(toUtcMs('2026-10-09T20:03:12+07:00'), Date.UTC(2026, 9, 9, 13, 3, 12))
  assert.equal(toUtcMs('2026-10-09T13:05:04'), Date.UTC(2026, 9, 9, 13, 5, 4))
  assert.equal(toUtcMs('2026-02-30'), null)
  assert.equal(toUtcMs(null), null)
  assert.equal(toUtcMs('soon'), null)
})
