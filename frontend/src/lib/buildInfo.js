/**
 * App version and commit, for the citation and the reproducibility block.
 *
 * Data source: build-time constants `__APP_VERSION__` (package.json
 * `version`) and `__GIT_SHA__` (`git rev-parse --short HEAD`) injected by
 * Vite `define` in vite.config.js.
 *
 * Limitations: outside a Vite build (plain Node tests, or a build without
 * git) both fall back to "dev". The SHA names the commit the build started
 * from; it does not say whether the working tree had uncommitted changes.
 */
/* global __APP_VERSION__, __GIT_SHA__ */

const FALLBACK = 'dev'

const clean = (value) => (typeof value === 'string' && value.trim() !== '' ? value.trim() : FALLBACK)

export const appVersion = clean(typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : undefined)
export const gitSha = clean(typeof __GIT_SHA__ !== 'undefined' ? __GIT_SHA__ : undefined)
