/**
 * useBaseline(): which seasonal baseline the server has in force, read once
 * from `GET /methods` and shared by every component that asks.
 *
 * Data source: `GET /methods` -> `baseline` (backend/src/schemas.py
 * MethodsBaselineStatus: `mode` 'off'|'test', `valid`, `kind`, `version`,
 * `reason`) and the response's `disclaimer` (server text, verbatim).
 *
 * State: `{status, mode, valid, kind, version, reason, isTest, disclaimer,
 * methods, error}`
 *   - status 'loading' | 'ready' | 'error';
 *   - `isTest` is true only for mode 'test' AND valid === true. Test mode
 *     with an invalid artefact is `isTest: false` with `reason` set, so the
 *     UI can say a TEST baseline is switched on but cannot be used;
 *   - a failed request is `status: 'error'`, `isTest: false` -- the pages
 *     never wait on this and never block; the shell shows an inline note.
 *     Each response that carries anomaly values also carries its own
 *     `baseline` block, which stays the authority for those values.
 *   - `methods` is the raw response (for the Methods/Data pages), or null.
 *
 * Caching: one module-level request promise and one published snapshot
 * (useSyncExternalStore), so the shell and every page share one request and
 * a page mounted later reads the answer synchronously. A failure is not
 * cached: the next caller (e.g. the next page mount) retries.
 * `resetBaselineCache()` is the test seam; `loadBaseline(fetcher)` takes a
 * fetcher for tests (default: the real `getMethods`).
 *
 * Limitations: read once per page load; a server restarted with a different
 * BASELINE_MODE is noticed on reload.
 */
import { useEffect, useSyncExternalStore } from 'react'
import { getMethods } from '../api/client.js'

const isObject = (v) => v !== null && typeof v === 'object'
const text = (v) => (typeof v === 'string' && v.trim() !== '' ? v : null)

export const BASELINE_LOADING = Object.freeze({
  status: 'loading',
  mode: null,
  valid: null,
  kind: null,
  version: null,
  reason: null,
  isTest: false,
  disclaimer: null,
  methods: null,
  error: null,
})

/** A `/methods` response -> the baseline state (pure). */
export function baselineFromMethods(methods) {
  const block = isObject(methods) && isObject(methods.baseline) ? methods.baseline : {}
  const mode = block.mode === 'test' || block.mode === 'off' ? block.mode : null
  const valid = typeof block.valid === 'boolean' ? block.valid : null
  return Object.freeze({
    status: 'ready',
    mode,
    valid,
    kind: text(block.kind),
    version: text(block.version),
    reason: text(block.reason),
    isTest: mode === 'test' && valid === true,
    disclaimer: isObject(methods) ? text(methods.disclaimer) : null,
    methods: isObject(methods) ? methods : null,
    error: null,
  })
}

function errorState(error) {
  const status = error?.response?.status
  return Object.freeze({
    ...BASELINE_LOADING,
    status: 'error',
    error: Object.freeze({
      status: Number.isInteger(status) ? status : null,
      message: typeof error?.message === 'string' ? error.message : String(error),
    }),
  })
}

let snapshot = BASELINE_LOADING
let pending = null
let generation = 0
const listeners = new Set()

function publish(next) {
  snapshot = next
  for (const listener of listeners) listener()
}

/** Start (or join) the one `/methods` request; resolves to the new state. */
export function loadBaseline(fetcher = getMethods) {
  if (pending) return pending
  const mine = generation
  const settle = (next, keep) => {
    if (mine !== generation) return next // reset meanwhile: do not publish into the new store
    if (!keep) pending = null
    publish(next)
    return next
  }
  pending = Promise.resolve()
    .then(() => fetcher())
    .then((methods) => settle(baselineFromMethods(methods), true), (error) => settle(errorState(error), false))
  return pending
}

/** Test seam: forget the request and the answer. */
export function resetBaselineCache() {
  generation += 1
  pending = null
  publish(BASELINE_LOADING)
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

const getSnapshot = () => snapshot

export function useBaseline() {
  const state = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  useEffect(() => {
    loadBaseline()
  }, [])
  return state
}
