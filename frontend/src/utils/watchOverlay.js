const ALERT_LEVELS = new Set(['elevated', 'watch', 'warning'])
const ALERT_MODES = new Set(['true_color', 'watch'])
const DEFAULT_LEVEL_COLORS = {
  elevated: '#34C759',
  watch: '#FF9F0A',
  warning: '#FF3B30',
}
const HEX_COLOR = /^#[0-9a-f]{6}$/i

export function canRenderWatchTiles(mode, overlay) {
  return mode === 'watch' && Boolean(overlay?.tile_url)
}

export function getVisibleSiteAlerts(mode, overlay) {
  if (!ALERT_MODES.has(mode) || !overlay?.tile_url) return []
  const metadata = overlay?.analysis_metadata
  if (metadata?.version !== 2 || !Array.isArray(metadata.site_alerts)) return []
  return metadata.site_alerts.filter((item) => (
    ALERT_LEVELS.has(item?.level)
    && Number.isFinite(item?.lat)
    && Number.isFinite(item?.lng)
  ))
}

export function getOverlayLegendLevels(mode, overlay) {
  if (!ALERT_MODES.has(mode)) return []
  const metadata = overlay?.analysis_metadata
  if (metadata?.version !== 2 || !Array.isArray(metadata.levels)) return []
  return metadata.levels.filter((item) => ALERT_LEVELS.has(item?.code))
}

export function getSafeWatchColor(color, level) {
  if (typeof color === 'string' && HEX_COLOR.test(color)) return color
  return DEFAULT_LEVEL_COLORS[level] ?? DEFAULT_LEVEL_COLORS.watch
}

export function getWatchOverlayMessage(overlay, requestError = null) {
  if (requestError) return 'ชั้นข้อมูล NDCI watch ยังไม่พร้อมใช้งาน'
  if (!overlay) return 'กำลังโหลดชั้นข้อมูล NDCI watch…'
  if (overlay.tile_url && overlay.stale) return 'กำลังแสดงข้อมูลล่าสุดที่แคชไว้ (ข้อมูลเก่า)'
  if (overlay.tile_url) return null
  if (overlay.status === 'no_imagery') return 'ไม่มีภาพ Sentinel-2 ที่ใช้ได้ในช่วง 30 วันล่าสุด'
  return 'ชั้นข้อมูล NDCI watch ยังไม่พร้อมใช้งาน'
}
