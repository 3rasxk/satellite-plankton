export function canRenderWatchTiles(mode, overlay) {
  return mode === 'watch' && Boolean(overlay?.tile_url)
}

export function getWatchOverlayMessage(overlay, requestError = null) {
  if (requestError) return 'ชั้นข้อมูล NDCI watch ยังไม่พร้อมใช้งาน'
  if (!overlay) return 'กำลังโหลดชั้นข้อมูล NDCI watch…'
  if (overlay.tile_url && overlay.stale) return 'กำลังแสดงข้อมูลล่าสุดที่แคชไว้ (ข้อมูลเก่า)'
  if (overlay.tile_url) return null
  if (overlay.status === 'no_imagery') return 'ไม่มีภาพ Sentinel-2 ที่ใช้ได้ในช่วง 30 วันล่าสุด'
  return 'ชั้นข้อมูล NDCI watch ยังไม่พร้อมใช้งาน'
}
