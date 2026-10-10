/**
 * Which i18n text stands for which section of LIMITATIONS.md (repo root).
 *
 * Data source: static. `/data` shows a Thai/English summary of
 * LIMITATIONS.md from the dictionaries (`limits.<id>.title`, `limits.<id>.p1`
 * ...); this file is the index that ties each summary to the exact `##`
 * heading it summarises, so a section added to LIMITATIONS.md without a
 * summary fails tests/data_model.test.js (it reads the file's headings and
 * compares them with `heading` below).
 *
 * Sections with `source: 'test-baseline-spec'` are not in LIMITATIONS.md:
 * they are the TEST-baseline limits of docs/superpowers/specs/
 * 2026-10-09-test-baseline-and-latest-scene-design.md §8 (and the quality
 * screens `/methods` reports), kept apart so the page never presents them
 * as part of LIMITATIONS.md.
 *
 * Limitations: summaries are shorter than the file and carry no numbers;
 * the file and `/methods` remain the authority for every value.
 */

const points = (id, n) => Object.freeze(Array.from({ length: n }, (_, i) => `limits.${id}.p${i + 1}`))

const section = (id, heading, source, count) => Object.freeze({
  id,
  heading,
  source,
  titleKey: `limits.${id}.title`,
  pointKeys: points(id, count),
})

export const LIMITATIONS_FILE = 'LIMITATIONS.md'
export const TEST_BASELINE_SPEC = 'test-baseline-spec'

export const LIMITATIONS_SECTIONS = Object.freeze([
  section('truth_boundary', 'Truth boundary', LIMITATIONS_FILE, 4),
  section('sensor_limits', 'Sensor and interpretation limits', LIMITATIONS_FILE, 9),
  section('no_anomaly_layer', 'No spectral-index anomaly layer is active', LIMITATIONS_FILE, 4),
  section('threshold_register', 'Numerical threshold register', LIMITATIONS_FILE, 4),
  section('references', 'Scientific references and transfer limits', LIMITATIONS_FILE, 2),
  section('pipeline', 'Data-pipeline findings', LIMITATIONS_FILE, 3),
  section('interpretation', 'Plain interpretation', LIMITATIONS_FILE, 4),
  section('test_baseline', 'TEST baseline limits', TEST_BASELINE_SPEC, 8),
])

/** Every i18n key the limitations block uses. */
export const LIMITATIONS_KEYS = Object.freeze(
  LIMITATIONS_SECTIONS.flatMap((s) => [s.titleKey, ...s.pointKeys]),
)
