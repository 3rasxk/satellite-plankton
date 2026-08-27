import test from 'node:test'
import assert from 'node:assert/strict'

import {
  canRenderWatchTiles,
  getOverlayLegendLevels,
  getVisibleSiteAlerts,
  getWatchOverlayMessage,
} from '../src/utils/watchOverlay.js'

const overlay = {
  status: 'ok',
  tile_url: 'https://tiles.example/{z}/{x}/{y}',
  analysis_metadata: {
    version: 2,
    levels: [
      { code: 'elevated', class_code: 1, label_th: 'เริ่มผิดปกติ', color: '#34C759' },
      { code: 'watch', class_code: 2, label_th: 'เฝ้าระวัง', color: '#FF9F0A' },
      { code: 'warning', class_code: 3, label_th: 'เตือนภัย', color: '#FF3B30' },
    ],
    site_alerts: [
      { site_id: 'normal', level: 'normal', lat: 13, lng: 100 },
      { site_id: 'elevated', level: 'elevated', lat: 13.1, lng: 100.1, color: '#34C759' },
      { site_id: 'warning', level: 'warning', lat: 13.2, lng: 100.2, color: '#FF3B30' },
      { site_id: 'bad-coordinates', level: 'watch', lat: null, lng: 100.3, color: '#FF9F0A' },
    ],
  },
}

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

test('shows only valid non-normal pins in True Color and scan modes', () => {
  assert.deepEqual(getVisibleSiteAlerts('true_color', overlay).map((item) => item.site_id), ['elevated', 'warning'])
  assert.deepEqual(getVisibleSiteAlerts('watch', overlay).map((item) => item.site_id), ['elevated', 'warning'])
  assert.deepEqual(getVisibleSiteAlerts('ndci', overlay), [])
})

test('does not invent pins or a three-tier legend for legacy metadata', () => {
  assert.deepEqual(getVisibleSiteAlerts('watch', { ...overlay, analysis_metadata: null }), [])
  assert.deepEqual(getOverlayLegendLevels('watch', { ...overlay, analysis_metadata: null }), [])
})

test('requires a version-two metadata shape and a tile for pins', () => {
  assert.deepEqual(getVisibleSiteAlerts('watch', { ...overlay, tile_url: null }), [])
  assert.deepEqual(getVisibleSiteAlerts('watch', {
    ...overlay,
    analysis_metadata: { ...overlay.analysis_metadata, version: 1 },
  }), [])
  assert.deepEqual(getOverlayLegendLevels('watch', {
    ...overlay,
    analysis_metadata: { ...overlay.analysis_metadata, version: 1 },
  }), [])
  assert.deepEqual(getVisibleSiteAlerts('watch', {
    ...overlay,
    analysis_metadata: { ...overlay.analysis_metadata, site_alerts: {} },
  }), [])
})

test('legend contains only the three approved abnormal levels', () => {
  assert.deepEqual(getOverlayLegendLevels('true_color', overlay).map((item) => item.code), ['elevated', 'watch', 'warning'])
})
