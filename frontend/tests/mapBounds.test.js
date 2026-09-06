import test from 'node:test'
import assert from 'node:assert/strict'

import { MAP_BOUNDS, syncMinimumBoundsZoom } from '../src/utils/mapBounds.js'

test('allows the whole Gulf boundary to fit within the viewport', () => {
  const expectedBounds = [
    [6.30, 99.00],
    [13.80, 103.20],
  ]
  const state = { minZoom: null, zoom: 7 }
  const map = {
    getBoundsZoom(bounds, inside) {
      assert.deepEqual(bounds, expectedBounds)
      assert.equal(inside, false)
      return 8
    },
    setMinZoom(zoom) {
      state.minZoom = zoom
    },
    getZoom() {
      return state.zoom
    },
    setZoom(zoom) {
      state.zoom = zoom
    },
  }

  const minZoom = syncMinimumBoundsZoom(map, MAP_BOUNDS)

  assert.equal(minZoom, 8)
  assert.deepEqual(state, { minZoom: 8, zoom: 8 })
})

test('a smaller fit zoom after resizing is not clamped by the previous minimum', () => {
  const state = { minZoom: 9, zoom: 9 }
  const map = {
    getBoundsZoom() {
      // Leaflet clamps its computed fit zoom to the current minZoom.
      return Math.max(6, state.minZoom)
    },
    setMinZoom(zoom) { state.minZoom = zoom },
    getZoom() { return state.zoom },
    setZoom(zoom) { state.zoom = zoom },
  }
  assert.equal(syncMinimumBoundsZoom(map, MAP_BOUNDS), 6)
  assert.equal(state.minZoom, 6)
})
