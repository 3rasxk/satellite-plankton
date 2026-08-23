// Shared copy + risk-level mappings. Colour tokens themselves live in
// styles/tokens.css — this file only maps API enum values to those tokens
// and to human copy, per docs/FRONTEND_PLAN.md §6 (interface words are
// design material, write from the reader's side).

// Verbatim truth-boundary text, matches backend/src/schemas.py
// DISCLAIMER_TEXT exactly. Used as the persistent banner default so it is
// visible even before any fetch resolves — never dropped, never tied to
// load state.
export const DISCLAIMER_TEXT =
  'Detection is at satellite-pixel resolution. Small or scattered blooms may not be visible. Presence and absence are the reliable signal — concentration estimates are approximate.'

// risk_level enum -> risk-ramp colour. Four published tiers map onto the
// four risk tokens 1:1 — see docs/FRONTEND_PLAN.md §4. Apple-palette
// redesign: normal is a neutral grey (kept off the accent blue, which is
// reserved for interactive elements only), elevated/watch/warning are
// Apple systemGreen/systemOrange/systemRed — same tier order as the old
// dark-theme ramp, new hues.
export const RISK_COLOR_VAR = {
  normal: '--risk-normal',
  elevated: '--risk-elevated',
  watch: '--risk-watch',
  warning: '--risk-warning',
}

// Same ramp as RISK_COLOR_VAR, as literal hex — Leaflet's SVG/Canvas
// renderer paints via a raw colour string (fillColor/color), which does
// NOT resolve CSS custom properties the way DOM `style` does, so map
// markers need the literal value. Keep in sync with styles/tokens.css by
// hand; both are small and rarely change.
export const RISK_COLOR_HEX = {
  normal: '#8E8E93',
  elevated: '#34C759',
  watch: '#FF9F0A',
  warning: '#FF3B30',
}

export const NO_DATA_HEX = '#E5E5EA'
export const NO_DATA_LINE_HEX = '#AEAEB2'

export const RISK_LABEL = {
  normal: 'Normal',
  elevated: 'Elevated',
  watch: 'Watch',
  warning: 'Warning',
}

export const RISK_MEANING = {
  normal: 'Chlorophyll near the seasonal baseline for this site.',
  elevated: 'Chlorophyll above baseline — one rule-based signal triggered.',
  watch: 'Multiple signals elevated — indicative of rising bloom risk.',
  warning: 'Strong, multi-signal anomaly — highest indicative risk tier.',
}

// detect()/cache status values that mean "no reading", never merged with
// a real risk_level colour. status: "ok" is the only one that gets a
// ramp colour; everything else gets the neutral no-data treatment.
export const NO_DATA_STATUS = new Set([
  'no_imagery',
  'no_water_pixels',
  'no_climatology',
  'no_data_yet',
  'error',
])

export const STATUS_LABEL = {
  ok: 'Reading available',
  no_imagery: 'No satellite pass',
  no_water_pixels: 'No water pixels in sample',
  no_climatology: 'No baseline yet for this date',
  no_data_yet: 'Not checked yet',
  error: 'Last refresh failed',
}

export const STATUS_EXPLAINER = {
  no_imagery: 'Cloud cover or orbit gap blocked a usable satellite pass — this is not the same as a clear reading.',
  no_water_pixels: 'The sample area returned no water pixels for this date — likely land/cloud mask overlap.',
  no_climatology: 'MODIS climatology has no baseline for this day-of-year at this site yet.',
  no_data_yet: 'The scheduler has not completed its first refresh for this site.',
  error: 'The scheduler\'s last refresh attempt for this site failed — showing the last successful reading, marked stale.',
}

// Bucketing anomaly_z onto the same ramp used by risk_level, for the
// AnomalyStrip. This is a display convention (z <= 0 reads as clear,
// z > 2 as severe) — not a rule from detection/src/config.yaml, and never
// presented as a calibrated threshold.
export function zToColorVar(z) {
  if (z === null || z === undefined) return null
  if (z <= 0) return '--risk-normal'
  if (z <= 1) return '--risk-elevated'
  if (z <= 2) return '--risk-watch'
  return '--risk-warning'
}

export function formatZ(z) {
  if (z === null || z === undefined) return '—'
  return z.toFixed(2)
}

// Plain-language text for each triggered_rules entry. `/risk-map` and
// `/detect` return level names only (e.g. "watch"), not the rule's
// condition text — mirrors detection/src/config.yaml `escalation_rules.*
// .description` verbatim so a viewer never has to read raw condition
// syntax like "anomaly_z >= 1.5". Kept in sync manually with that file;
// there is no API field that exposes the description text itself.
export const RULE_DESCRIPTION = {
  elevated: 'Chlorophyll anomaly is at least 1.5 standard deviations above the seasonal norm.',
  watch: 'Anomaly is elevated and the 14-day trend is rising.',
  warning:
    'Anomaly has reached 2.0 std above normal, the 14-day trend is rising, and sea surface temperature is above its seasonal normal.',
}

// "Updated 4 hours ago" not "Last sync: 2026-08-17T04:00:00Z" — copy rule
// in docs/FRONTEND_PLAN.md §6.
export function formatRelativeTime(isoString) {
  if (!isoString) return 'unknown'
  const then = new Date(isoString).getTime()
  if (Number.isNaN(then)) return 'unknown'
  const diffMs = Date.now() - then
  const minutes = Math.round(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

export function formatConfidence(label) {
  // Never render a raw float as a percentage (no fake precision) — the
  // backend already sends a word/phrase (confidence_label), this just
  // guards against an unexpected numeric value slipping through.
  if (typeof label === 'number') {
    if (label >= 0.66) return 'high confidence'
    if (label >= 0.33) return 'moderate confidence'
    return 'low confidence'
  }
  return label || 'confidence not stated'
}
