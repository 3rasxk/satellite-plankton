import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRiskMap, getWatchOverlay } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import RiskLegend from '../components/RiskLegend.jsx'
import MapControls from '../components/MapControls.jsx'
import { formatRelativeTime } from '../constants.js'
import Icon from '../components/Icon.jsx'
import { getWatchOverlayMessage } from '../utils/watchOverlay.js'

function WatchOverlayState({ loading, overlay, error, onRetry }) {
  const message = getWatchOverlayMessage(overlay, error)
  const hasTiles = Boolean(overlay?.tile_url)
  const sourceWindow = overlay?.source_window_start && overlay?.source_window_end
    ? `${overlay.source_window_start} – ${overlay.source_window_end}`
    : null
  const errorDetail = error?.message || (!hasTiles ? overlay?.error : null)

  return (
    <div className="watch-overlay-state glass" role="status" aria-live="polite" aria-atomic="true">
      {loading ? (
        <span>กำลังโหลดชั้นข้อมูล NDCI watch…</span>
      ) : (
        <>
          <span>{message || 'NDCI watch พร้อมใช้งาน'}</span>
          {hasTiles && sourceWindow && <span>ช่วงภาพ {sourceWindow}</span>}
          {hasTiles && overlay.newest_scene_date && <span>ฉากล่าสุด {overlay.newest_scene_date}</span>}
          {hasTiles && <span>พิกเซลโมเสกอาจมาจากหลายวันที่แตกต่างกัน</span>}
          {errorDetail && <span>{errorDetail}</span>}
          {!hasTiles && <button type="button" className="watch-overlay-retry" onClick={onRetry}>ลองใหม่</button>}
        </>
      )}
    </div>
  )
}

export default function OverviewPage() {
  const { data: riskData } = useApi(getRiskMap, [])
  const {
    data: watchOverlay,
    loading: watchLoading,
    error: watchError,
    refetch: refetchWatch,
  } = useApi(getWatchOverlay, [])
  const [mode, setMode] = useState('true_color')

  const newestFetch = useMemo(() => {
    const times = (riskData?.features || []).map((f) => f.properties.fetched_at).filter(Boolean).sort()
    return times.length ? times[times.length - 1] : null
  }, [riskData])

  return (
    <div className="overview-page">
      <div className="overview-map-area">
        <RiskMap mode={mode} watchOverlay={watchOverlay} />
        <MapControls mode={mode} onModeChange={setMode} />
        <RiskLegend mode={mode} watchOverlay={watchOverlay} />
        <div className="map-date-pill glass">
          <Icon name="calendar" size={15} />
          {newestFetch ? `อัปเดต ${formatRelativeTime(newestFetch)}` : 'Sentinel-2 + MODIS'}
          <Icon name="chevronDown" size={14} />
        </div>
        {mode === 'watch' && <WatchOverlayState loading={watchLoading} overlay={watchOverlay} error={watchError} onRetry={refetchWatch} />}
      </div>
    </div>
  )
}
