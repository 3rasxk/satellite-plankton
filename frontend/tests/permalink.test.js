/**
 * encodeView / decodeView: a URL that reopens the exact view a judge saw.
 *
 * The decoder is the input boundary (anyone can paste a URL), so garbage
 * is dropped key by key rather than trusted or thrown on; and the encoder
 * only ever writes the seven view keys, so nothing personal can travel in
 * a shared link.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { encodeView, decodeView, LAYERS, VIEW_PARAMS } from '../src/lib/permalink.js'

test('encodeView writes the view keys in a fixed order', () => {
  assert.deepEqual([...VIEW_PARAMS], ['lat', 'lng', 'run', 'layer', 'zoom', 'pin', 'lang'])
  assert.deepEqual([...LAYERS], ['ndci', 'light_map', 'true_color'])
  assert.equal(
    encodeView({ lang: 'en', pin: 2, zoom: 10, layer: 'ndci', runId: 6, lng: 100.6, lat: 13 }),
    'lat=13&lng=100.6&run=6&layer=ndci&zoom=10&pin=2&lang=en',
  )
  assert.equal(encodeView({}), '')
  assert.equal(encodeView(), '')
})

test('coordinates are rounded to 6 decimals (about 0.1 m)', () => {
  assert.equal(encodeView({ lat: 12.999520476493597, lng: 100.59963372269286 }),
    'lat=12.99952&lng=100.599634')
  assert.equal(encodeView({ lat: -8.1234567, lng: -100.5 }), 'lat=-8.123457&lng=-100.5')
})

test('round trip: decode(encode(view)) returns the same view', () => {
  const views = [
    { lat: 13, lng: 100.6, runId: 6, layer: 'ndci', zoom: 10, pin: 2, lang: 'en' },
    { lat: 12.692297, lng: 100.355292, layer: 'true_color' },
    { runId: 12, pin: 10, lang: 'th' },
    { layer: 'light_map', zoom: 8.5 },
    {},
  ]
  for (const view of views) {
    assert.deepEqual(decodeView(encodeView(view)), view, JSON.stringify(view))
    assert.deepEqual(decodeView(`?${encodeView(view)}`), view)
    assert.deepEqual(decodeView(new URLSearchParams(encodeView(view))), view)
  }
})

test('decodeView drops garbage key by key', () => {
  const cases = [
    ['lat=abc&lng=100', {}],
    ['lat=91&lng=100', {}],
    ['lat=13&lng=181', {}],
    ['lat=13', {}],
    ['lng=100', {}],
    ['lat=13&lng=', {}],
    ['lat=Infinity&lng=100', {}],
    ['lat=1e1&lng=100', {}],
    ['lat=0x10&lng=100', {}],
    ['lat= 13&lng=100', {}],
    ['run=-1', {}],
    ['run=0', {}],
    ['run=1.5', {}],
    ['run=abc', {}],
    ['run=99999999999999999999', {}],
    ['layer=risk', {}],
    ['layer=NDCI', {}],
    ['zoom=99', {}],
    ['zoom=-1', {}],
    ['zoom=abc', {}],
    ['pin=0', {}],
    ['pin=11', {}],
    ['pin=2.5', {}],
    ['lang=fr', {}],
    ['lat=13&lng=100&layer=evil&run=6', { lat: 13, lng: 100, runId: 6 }],
  ]
  for (const [search, expected] of cases) {
    assert.deepEqual(decodeView(search), expected, search)
  }
  assert.deepEqual(decodeView(undefined), {})
  assert.deepEqual(decodeView(null), {})
  assert.deepEqual(decodeView(42), {})
  assert.deepEqual(decodeView('%E0%A4%A'), {})
})

test('encodeView refuses invalid values instead of writing them', () => {
  assert.equal(encodeView({ lat: Number.NaN, lng: 100 }), '')
  assert.equal(encodeView({ lat: 95, lng: 100 }), '')
  assert.equal(encodeView({ runId: 0, layer: 'risk', zoom: 40, pin: 11, lang: 'fr' }), '')
  assert.equal(encodeView({ runId: '6' }), '')
})

test('nothing but the view keys can travel in a link', () => {
  const q = encodeView({ lat: 13, lng: 100.6, email: 'judge@example.org', name: 'A. Judge', token: 'secret' })
  assert.equal(q, 'lat=13&lng=100.6')
  const v = decodeView('lat=13&lng=100.6&email=judge@example.org&token=secret')
  assert.deepEqual(v, { lat: 13, lng: 100.6 })
})
