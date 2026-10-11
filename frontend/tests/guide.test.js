/**
 * The reading guide's first-visit rule (src/lib/guide.js): it opens by
 * itself only when storage is readable and has no "seen" flag; a storage
 * that is missing or throws on every access never breaks the page and
 * never makes the guide reappear on every load.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  GUIDE_STORAGE_KEY, GUIDE_SEEN_VALUE, GUIDE_STEPS, shouldAutoOpenGuide, markGuideSeen, clampStep,
} from '../src/lib/guide.js'

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial))
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => { data.set(k, String(v)) },
    data,
  }
}

const throwingStorage = {
  getItem() { throw new Error('SecurityError: storage is blocked') },
  setItem() { throw new Error('QuotaExceededError') },
}

test('first visit: an empty storage opens the guide; once marked it stays closed', () => {
  const storage = memoryStorage()
  assert.equal(shouldAutoOpenGuide(storage), true)
  assert.equal(markGuideSeen(storage), true)
  assert.equal(storage.data.get(GUIDE_STORAGE_KEY), GUIDE_SEEN_VALUE)
  assert.equal(shouldAutoOpenGuide(storage), false)
})

test('an unrelated value under the key is not "seen"', () => {
  assert.equal(shouldAutoOpenGuide(memoryStorage({ [GUIDE_STORAGE_KEY]: 'nope' })), true)
})

test('a storage that throws: no exception, no automatic opening, the write reports failure', () => {
  assert.doesNotThrow(() => shouldAutoOpenGuide(throwingStorage))
  assert.equal(shouldAutoOpenGuide(throwingStorage), false)
  assert.doesNotThrow(() => markGuideSeen(throwingStorage))
  assert.equal(markGuideSeen(throwingStorage), false)
})

test('no storage at all (SSR, previews): the guide does not open by itself', () => {
  for (const s of [null, undefined, {}, { getItem: 'x' }]) {
    assert.equal(shouldAutoOpenGuide(s), false)
    assert.equal(markGuideSeen(s), false)
  }
})

test('three steps; the step index is clamped', () => {
  assert.deepEqual([...GUIDE_STEPS], ['colours', 'select', 'estimates'])
  assert.equal(clampStep(0, -1), 0)
  assert.equal(clampStep(0, 1), 1)
  assert.equal(clampStep(2, 1), 2)
  assert.equal(clampStep('x', 1), 0)
})
