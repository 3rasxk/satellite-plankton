import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRiskMap } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import RiskLegend from '../components/RiskLegend.jsx'
import MapControls from '../components/MapControls.jsx'
import SitePanel from '../components/SitePanel.jsx'
import { formatRelativeTime } from '../constants.js'

export default function OverviewPage() {
  const { data, loading, error, refetch } = useApi(getRiskMap, [])
  const [selected, setSelected] = useState(null)
  const [mode, setMode] = useState('risk')

  const newestFetch = useMemo(() => {
    if (!data) return null
    const times = data.features.map((f) => f.properties.fetched_at).filter(Boolean).sort()
    return times.length ? times[times.length - 1] : null
  }, [data])

  return (
    <div className="overview-page">
      <div className="overview-map-area">
        {loading && <div className="state-panel" style={{ margin: 24 }}><h3>Loading the monitored grid…</h3></div>}
        {error && (
          <div className="state-panel error" style={{ margin: 24 }}>
            <h3>Couldn&apos;t reach the data service.</h3>
            <button type="button" className="retry-btn" onClick={refetch}>Retry</button>
          </div>
        )}
        {data && data.features.length > 0 && (
          <>
            <RiskMap featureCollection={data} onSelectSite={setSelected} mode={mode} />
            <MapControls mode={mode} onModeChange={setMode} />
            <RiskLegend mode={mode} />
            <div className="map-date-pill glass">
              📅 {newestFetch ? `อัปเดต ${formatRelativeTime(newestFetch)}` : 'Sentinel-2 + MODIS'} ⌄
            </div>
          </>
        )}
      </div>
      <div className="overview-side-panel">
        {selected ? (
          <SitePanel site={selected} onClose={() => setSelected(null)} />
        ) : (
          <div className="state-panel"><h3>เลือกจุดตรวจวัดบนแผนที่</h3></div>
        )}
      </div>
    </div>
  )
}
