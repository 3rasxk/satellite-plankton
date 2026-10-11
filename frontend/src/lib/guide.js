/**
 * guide: first-visit logic of the reading guide (src/components/ui/ReadingGuide.jsx)
 * and its step list, kept pure so it runs under `node --test`.
 *
 * Data source: the browser's `localStorage` only, passed in (never read
 * from a global here). Storage can be missing or throw on every access in
 * private windows, with blocked site data, in previews or during thumbnail
 * capture, so every read and write is wrapped in try/catch.
 *
 * Rule: the guide opens by itself only when storage is readable and says
 * it has not been seen. When storage cannot be read the guide does not open
 * by itself -- it could never be remembered as closed and would reappear on
 * every page load -- but the help button still opens it.
 *
 * Limitations: a per-browser convenience; it stores one flag and nothing
 * about the reader.
 */

export const GUIDE_STORAGE_KEY = 'plankton.guide.seen'
export const GUIDE_SEEN_VALUE = '1'

/** The three steps, in order: i18n keys under `guide.steps.<id>`. */
export const GUIDE_STEPS = Object.freeze(['colours', 'select', 'estimates'])

/** The `localStorage` of this window, or null when it cannot be reached. */
export function browserStorage() {
  try {
    return typeof window !== 'undefined' && window.localStorage ? window.localStorage : null
  } catch {
    return null
  }
}

/** True only when `storage` is readable and holds no "seen" flag. */
export function shouldAutoOpenGuide(storage) {
  if (!storage || typeof storage.getItem !== 'function') return false
  try {
    return storage.getItem(GUIDE_STORAGE_KEY) !== GUIDE_SEEN_VALUE
  } catch {
    return false
  }
}

/** Remember that the guide was seen. Returns whether the write succeeded;
 * never throws. */
export function markGuideSeen(storage) {
  if (!storage || typeof storage.setItem !== 'function') return false
  try {
    storage.setItem(GUIDE_STORAGE_KEY, GUIDE_SEEN_VALUE)
    return true
  } catch {
    return false
  }
}

/** The step index after `step` moves by `delta`, clamped to the list. */
export function clampStep(step, delta = 0) {
  const n = Number.isInteger(step) ? step + (Number.isInteger(delta) ? delta : 0) : 0
  return Math.min(GUIDE_STEPS.length - 1, Math.max(0, n))
}
