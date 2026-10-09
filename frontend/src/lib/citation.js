/**
 * buildCitation: a plain-text citation of exactly what was seen (dashboard
 * spec §5 `CiteButton`).
 *
 * Data source: build info (src/lib/buildInfo.js), the served raster run and
 * its scene-date span (`/raster-scan` run_id, oldest_scene_date,
 * newest_scene_date), the TEST baseline version when one is in force
 * (`baseline.version`), the access date and the permalink.
 *
 * Shape: "Plankton Watch (v<version>, <sha>), raster run <id>, scenes
 * <oldest>–<newest>[, TEST baseline <version>], accessed <date>. <permalink>"
 * -- labels from i18n `citation.*`, dates ISO in UTC, unknowns "—".
 *
 * Limitations: provenance only. It names the software, data run and date;
 * it makes no statement about what the data show.
 */
import { createT } from '../i18n/index.js'
import { NULL_TEXT, formatDateSpan, formatValue } from './format.js'

export const APP_NAME = 'Plankton Watch'

const known = (v) => (typeof v === 'string' && v.trim() !== '') || (typeof v === 'number' && Number.isFinite(v))

/** "v0.0.0" for a release-style version, the value as is otherwise ("dev"). */
function versionText(version) {
  if (!known(version)) return NULL_TEXT
  const v = String(version).trim()
  return /^\d/.test(v) ? `v${v}` : v
}

export function buildCitation(input) {
  const {
    lang, version, sha, runId, oldestScene, newestScene, accessedAt, permalink, baselineVersion,
  } = input !== null && typeof input === 'object' ? input : {}
  const t = createT(lang)
  const parts = [
    `${APP_NAME} (${versionText(version)}, ${known(sha) ? String(sha).trim() : NULL_TEXT})`,
    t('citation.raster_run', { run: known(runId) ? String(runId) : null }),
    t('citation.scenes', { span: formatDateSpan(oldestScene, newestScene) }),
  ]
  if (known(baselineVersion)) parts.push(t('citation.test_baseline', { version: String(baselineVersion).trim() }))
  parts.push(t('citation.accessed', { date: formatValue(accessedAt, { kind: 'date' }).text }))
  const sentence = `${parts.join(', ')}.`
  return typeof permalink === 'string' && permalink.trim() !== '' ? `${sentence} ${permalink.trim()}` : sentence
}
