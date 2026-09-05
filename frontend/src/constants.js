// Shared copy + risk-level mappings. Colour tokens themselves live in
// styles/tokens.css — this file only maps API enum values to those tokens
// and to human copy, per docs/FRONTEND_PLAN.md §6 (interface words are
// design material, write from the reader's side).

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

// Thai counterpart to RISK_LABEL — same 4 tiers, same meaning, translated
// copy only (not a new claim). Shared by every later Thai-copy screen
// (Tasks 3, 4, 5, 7) so the tier labels stay consistent across the app.
export const RISK_LABEL_TH = {
  normal: 'ปกติ',
  elevated: 'เริ่มผิดปกติ',
  watch: 'เฝ้าระวัง',
  warning: 'เตือนภัย',
}

export const RISK_MEANING = {
  normal: 'Chlorophyll near the seasonal baseline for this site.',
  elevated: 'Chlorophyll above baseline — one rule-based signal triggered.',
  watch: 'Multiple signals elevated — indicative of rising bloom risk.',
  warning: 'Strong, multi-signal anomaly — highest indicative risk tier.',
}

export const RISK_MEANING_TH = {
  normal: 'ปกติของฤดูกาล',
  elevated: 'สูงกว่าเกณฑ์ปกติ',
  watch: 'เสี่ยงเพิ่มขึ้นต่อเนื่อง',
  warning: 'เสี่ยงสูง พบผิดปกติมาก',
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

export const STATUS_LABEL_TH = {
  ok: 'มีข้อมูลการตรวจวัด',
  no_imagery: 'ไม่มีรอบโคจรดาวเทียมผ่านจุดนี้',
  no_water_pixels: 'ไม่พบพิกเซลผืนน้ำในบริเวณที่ตรวจ',
  no_climatology: 'ยังไม่มีข้อมูลฐานสำหรับวันที่นี้',
  no_data_yet: 'ยังไม่ได้เริ่มการตรวจสอบ',
  error: 'การซิงก์ข้อมูลรอบล่าสุดไม่สำเร็จ',
}

export const STATUS_EXPLAINER = {
  no_imagery: 'Cloud cover or orbit gap blocked a usable satellite pass — this is not the same as a clear reading.',
  no_water_pixels: 'The sample area returned no water pixels for this date — likely land/cloud mask overlap.',
  no_climatology: 'MODIS climatology has no baseline for this day-of-year at this site yet.',
  no_data_yet: 'The scheduler has not completed its first refresh for this site.',
  error: 'The scheduler\'s last refresh attempt for this site failed — showing the last successful reading, marked stale.',
}

export const STATUS_EXPLAINER_TH = {
  no_imagery: 'เมฆบดบังหนาแน่นหรือไม่มีรอบโคจรดาวเทียม Sentinel-2 ผ่านจุดนี้ในวันนี้',
  no_water_pixels: 'พื้นที่ตัวอย่างไม่พบพิกเซลผืนน้ำ อาจมีเมฆหนาหรือขอบเขตชายฝั่งบดบัง',
  no_climatology: 'ยังไม่มีข้อมูลค่าเฉลี่ยรายฤดูกาล (MODIS Climatology) สำหรับวันดังกล่าว',
  no_data_yet: 'ระบบยังไม่เริ่มรอบการตรวจสอบแรกสำหรับจุดตรวจวัดนี้',
  error: 'ระบบไม่สามารถดึงข้อมูลรอบล่าสุดได้ กำลังแสดงข้อมูลที่อ่านได้ล่าสุดแทน',
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

export const RULE_DESCRIPTION_TH = {
  elevated: 'คลอโรฟิลล์สูงกว่าค่าเฉลี่ยตามฤดูกาลเกิน 1.5 เท่าของส่วนเบี่ยงเบนมาตรฐาน (z ≥ 1.5)',
  watch: 'คลอโรฟิลล์สูงผิดปกติและแนวโน้ม 14 วันมีทิศทางเพิ่มขึ้นต่อเนื่อง',
  warning: 'คลอโรฟิลล์สูงมาก (z ≥ 2.0), แนวโน้มเพิ่มขึ้น และอุณหภูมิน้ำทะเลสูงกว่าปกติ',
}

const THAI_MONTHS_SHORT = [
  'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.',
  'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.',
]

export function formatThaiDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return dateStr
  const day = d.getDate()
  const month = THAI_MONTHS_SHORT[d.getMonth()]
  const year = d.getFullYear()
  return `${day} ${month} ${year}`
}

// "Updated 4 hours ago" not "Last sync: 2026-08-17T04:00:00Z" — copy rule
// in docs/FRONTEND_PLAN.md §6.
export function formatRelativeTime(isoString) {
  if (!isoString) return 'เมื่อสักครู่'
  const then = new Date(isoString).getTime()
  if (Number.isNaN(then)) return 'เมื่อสักครู่'
  const diffMs = Date.now() - then
  const minutes = Math.round(diffMs / 60000)
  if (minutes < 1) return 'เมื่อสักครู่'
  if (minutes < 60) return `${minutes} นาทีที่แล้ว`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} ชั่วโมงที่แล้ว`
  const days = Math.round(hours / 24)
  return `${days} วันที่แล้ว`
}

export const SITE_NAME_TH = {
  bangsaen: 'บางแสน, ชลบุรี',
  siracha: 'ศรีราชา, ชลบุรี',
  thachin_mouth: 'ปากแม่น้ำท่าจีน, สมุทรสาคร',
  chaophraya_mouth: 'ปากแม่น้ำเจ้าพระยา, สมุทรปราการ',
  chaam: 'ชายฝั่งชะอำ, เพชรบุรี',
  bangpakong_mouth: 'ปากแม่น้ำบางปะกง, ฉะเชิงเทรา',
  pattaya: 'หาดพัทยา, ชลบุรี',
  'Bang Saen, Chonburi': 'บางแสน, ชลบุรี',
  'Si Racha, Chonburi': 'ศรีราชา, ชลบุรี',
  'Tha Chin River mouth, Samut Sakhon': 'ปากแม่น้ำท่าจีน, สมุทรสาคร',
  'Chao Phraya River mouth, Samut Prakan': 'ปากแม่น้ำเจ้าพระยา, สมุทรปราการ',
  'Cha-am coast, Phetchaburi': 'ชายฝั่งชะอำ, เพชรบุรี',
  'Bang Pakong River mouth, Chachoengsao': 'ปากแม่น้ำบางปะกง, ฉะเชิงเทรา',
  'Pattaya Beach, Chonburi': 'หาดพัทยา, ชลบุรี',
}

export function formatSiteName(site) {
  if (!site) return ''
  if (typeof site === 'string') return SITE_NAME_TH[site] || site
  return (site.site_id && SITE_NAME_TH[site.site_id]) || (site.name && SITE_NAME_TH[site.name]) || site.name || ''
}

export function formatConfidence(label) {
  if (typeof label === 'number') {
    if (label >= 0.66) return 'ความเชื่อมั่นสูง'
    if (label >= 0.33) return 'ความเชื่อมั่นปานกลาง'
    return 'ความเชื่อมั่นต่ำ'
  }
  if (label === 'high confidence') return 'ความเชื่อมั่นสูง'
  if (label === 'moderate confidence') return 'ความเชื่อมั่นปานกลาง'
  if (label === 'low confidence') return 'ความเชื่อมั่นต่ำ'
  return label || 'ไม่ได้ระบุระดับความเชื่อมั่น'
}

// ---- Regional scan layer (GET /regional-scan) --------------------------
// Interim render: the regional scan currently publishes index readings
// only. `threshold_tier` is null on every point of the latest run (the
// anomaly cutoffs in detection/src/config.yaml are UNCALIBRATED, and no
// point cleared them), so RegionalScanLayer gates on a real index value
// instead and paints it with the neutral ramp below — never with
// RISK_COLOR_HEX, which means a published risk tier and nothing else.

// The index detect() treats as primary — detection/src/config.yaml
// `indices.primary: ndci`. RegionalScanPointSchema returns `index_values`
// but not `index_used`, so the key is named here rather than read from
// the response; keep in sync with that config field by hand.
export const REGIONAL_PRIMARY_INDEX = 'ndci'

export const REGIONAL_INDEX_LABEL = {
  ndci: 'NDCI',
  '2bda': '2BDA',
  '3bda': '3BDA',
  b2_b3_ratio: 'B2/B3',
}

// Neutral sequential ramp for an index magnitude — low to high. Kept
// deliberately outside the --risk-* ramp (which means a chlorophyll risk
// tier) and outside --accent (interactive elements only), per the rule at
// the top of styles/tokens.css. Literal hex because Leaflet paints from a
// raw colour string and does not resolve CSS custom properties; keep in
// sync with --regional-index-1..5 in tokens.css by hand.
export const REGIONAL_INDEX_RAMP_HEX = [
  '#dde5ee',
  '#b3c1d4',
  '#8497b3',
  '#586d8e',
  '#33445f',
]

/**
 * Colour domain for the ramp: the 5th–95th percentile of the primary
 * index across this run's own points, so a run whose values all sit in a
 * narrow band is still readable. This is a relative shading of one scan,
 * not an absolute scale — the legend states the endpoints so the reader
 * can see which numbers the shading spans. Returns null when the run
 * carries no usable primary-index value at all.
 */
export function regionalIndexDomain(points) {
  const values = (points || [])
    .map((p) => p.index_values?.[REGIONAL_PRIMARY_INDEX])
    .filter((v) => typeof v === 'number' && Number.isFinite(v))
    .sort((a, b) => a - b)
  if (values.length === 0) return null
  const at = (q) => values[Math.round(q * (values.length - 1))]
  let min = at(0.05)
  let max = at(0.95)
  if (min === max) {
    min = values[0]
    max = values[values.length - 1]
  }
  return { min, max, degenerate: min === max }
}

// Mid-ramp is the honest fallback when there is nothing to rank a point
// against (single-valued run) — never the darkest or lightest end, which
// would read as "extreme" on evidence the run does not carry.
export function regionalIndexColor(value, domain) {
  const ramp = REGIONAL_INDEX_RAMP_HEX
  const mid = ramp[Math.floor(ramp.length / 2)]
  if (typeof value !== 'number' || !Number.isFinite(value)) return mid
  if (!domain || domain.degenerate) return mid
  const t = (value - domain.min) / (domain.max - domain.min)
  const clamped = Math.min(1, Math.max(0, t))
  return ramp[Math.min(ramp.length - 1, Math.floor(clamped * ramp.length))]
}

export function formatIndexValue(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return value.toFixed(3)
}
