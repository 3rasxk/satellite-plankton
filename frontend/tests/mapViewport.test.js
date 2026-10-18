import test from 'node:test'
import assert from 'node:assert/strict'
import { fitPadding, labelSide, revealShift } from '../src/utils/mapViewport.js'

test('fit padding clears the rail, the top chips and the dock', () => {
  const p = fitPadding({ mapW: 1440, mapH: 900, railW: 344, topEdge: 180, dockH: 120 })
  assert.deepEqual(p.paddingTopLeft, [368, 180])
  assert.deepEqual(p.paddingBottomRight, [72, 120])
})

test('fit padding without a rail keeps a 24 px margin and never swallows the map', () => {
  assert.deepEqual(fitPadding({ mapW: 390, mapH: 844, topEdge: 180, dockH: 100 }).paddingTopLeft, [24, 180])
  const tiny = fitPadding({ mapW: 300, mapH: 300, railW: 344, topEdge: 180, dockH: 120 })
  assert.ok(tiny.paddingTopLeft[0] + tiny.paddingBottomRight[0] <= 300 * 0.7 + 1)
  assert.ok(tiny.paddingTopLeft[1] + tiny.paddingBottomRight[1] <= 300 * 0.7 + 1)
})

test('a label flips left when it would pass the limit', () => {
  assert.equal(labelSide({ x: 100, labelW: 200, rightLimit: 692 }), 'right')
  assert.equal(labelSide({ x: 600, labelW: 200, rightLimit: 692 }), 'left')
})

test('reveal leaves a visible pin alone and flips the label instead of panning', () => {
  const safe = { left: 24, right: 692, top: 120, bottom: 700 }
  assert.deepEqual(revealShift({ x: 300, y: 300, labelW: 200, safe }), { side: 'right', shiftX: 0, shiftY: 0 })
  assert.deepEqual(revealShift({ x: 650, y: 300, labelW: 200, safe }), { side: 'left', shiftX: 0, shiftY: 0 })
})

test('reveal pans a pin hidden under the inspector back into view', () => {
  const safe = { left: 24, right: 692, top: 120, bottom: 700 }
  const r = revealShift({ x: 800, y: 300, labelW: 200, safe })
  assert.equal(r.side, 'left')
  assert.equal(800 + 9 + r.shiftX, 692)
  const up = revealShift({ x: 300, y: 60, labelW: 0, safe })
  assert.equal(60 - 9 + up.shiftY, 120)
})
