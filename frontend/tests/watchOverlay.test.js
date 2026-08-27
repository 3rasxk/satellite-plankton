import test from 'node:test'
import assert from 'node:assert/strict'

import { canRenderWatchTiles, getWatchOverlayMessage } from '../src/utils/watchOverlay.js'

test('renders only a cached tile in watch mode', () => {
  const ready = { status: 'ok', tile_url: 'https://tiles.example/{z}/{x}/{y}', stale: false }
  assert.equal(canRenderWatchTiles('watch', ready), true)
  assert.equal(canRenderWatchTiles('true_color', ready), false)
  assert.equal(canRenderWatchTiles('watch', { ...ready, tile_url: null }), false)
})

test('never describes unavailable pixels as normal', () => {
  assert.match(getWatchOverlayMessage({ status: 'no_imagery', tile_url: null }), /ไม่มีภาพ|no imagery/i)
  assert.match(getWatchOverlayMessage({ status: 'error', tile_url: null, error: 'auth' }), /ไม่พร้อม|unavailable/i)
  assert.match(getWatchOverlayMessage({ status: 'ok', tile_url: 'x', stale: true }), /เก่า|stale/i)
})
