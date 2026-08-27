import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRiskMap } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import RiskLegend from '../components/RiskLegend.jsx'
import MapControls from '../components/MapControls.jsx'
import { formatRelativeTime } from '../constants.js'
import Icon from '../components/Icon.jsx'

export default function OverviewPage() {
  const { data, loading, error, refetch } = useApi(getRiskMap, [])
  const [mode, setMode] = useState('true_color')

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
            <RiskMap featureCollection={data} mode={mode} />
            <MapControls mode={mode} onModeChange={setMode} />
            <RiskLegend mode={mode} />
            <div className="map-date-pill glass">
              <Icon name="calendar" size={15} />
              {newestFetch ? `อัปเดต ${formatRelativeTime(newestFetch)}` : 'Sentinel-2 + MODIS'}
              <Icon name="chevronDown" size={14} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
