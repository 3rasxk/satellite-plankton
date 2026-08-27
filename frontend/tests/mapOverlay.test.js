import test from 'node:test'
import assert from 'node:assert/strict'

import {
  clampOverlayPosition,
  getDraggedOverlayPosition,
} from '../src/utils/mapOverlay.js'

test('dragging downward decreases a bottom-positioned overlay offset', () => {
  assert.deepEqual(getDraggedOverlayPosition(
    { x: 16, y: 40 },
    { x: 100, y: 100 },
    { x: 112, y: 125 },
  ), { x: 28, y: 15 })
})

test('clamps an overlay inside its container with an inset', () => {
  const container = { width: 320, height: 240 }
  const overlay = { width: 100, height: 80 }

  assert.deepEqual(
    clampOverlayPosition({ x: -20, y: 500 }, container, overlay, 8),
    { x: 8, y: 152 },
  )
  assert.deepEqual(
    clampOverlayPosition({ x: 500, y: -20 }, container, overlay, 8),
    { x: 212, y: 8 },
  )
})

test('keeps an oversized overlay anchored to the inset', () => {
  assert.deepEqual(
    clampOverlayPosition(
      { x: 40, y: 40 },
      { width: 80, height: 60 },
      { width: 120, height: 100 },
      8,
    ),
    { x: 8, y: 8 },
  )
})
