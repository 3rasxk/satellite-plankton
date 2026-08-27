import test from 'node:test'
import assert from 'node:assert/strict'

import { MAP_BOUNDS, syncMinimumBoundsZoom } from '../src/utils/mapBounds.js'

test('locks the minimum zoom to the supplied Gulf boundary', () => {
  const expectedBounds = [
    [12.06813056, 99.29500833],
    [13.92548889, 102.57761667],
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
