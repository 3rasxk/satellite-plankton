import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRiskMap } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import RiskLegend from '../components/RiskLegend.jsx'
import SitePanel from '../components/SitePanel.jsx'
import { formatRelativeTime } from '../constants.js'

export default function RiskMapPage() {
  const { data, loading, error, refetch } = useApi(getRiskMap, [])
  const [selected, setSelected] = useState(null)

  const newestFetch = useMemo(() => {
    if (!data) return null
    const times = data.features
      .map((f) => f.properties.fetched_at)
      .filter(Boolean)
      .sort()
    return times.length ? times[times.length - 1] : null
  }, [data])

  return (
    <div className="page">
      <div className="page-header">
        <h1>Algal bloom watch — upper Gulf of Thailand</h1>
        <span className="updated-line">
          {newestFetch
            ? `Updated ${formatRelativeTime(newestFetch)} · Sentinel-2 + MODIS`
            : 'Sentinel-2 + MODIS · monitored grid'}
        </span>
      </div>

      <div className="map-page-body">
        {loading && (
          <div className="state-panel" style={{ margin: 24 }}>
            <h3>Loading the monitored grid…</h3>
            <p>Fetching the latest cached risk reading for each site.</p>
          </div>
        )}

        {error && (
          <div className="state-panel error" style={{ margin: 24 }}>
            <h3>Couldn&apos;t reach the data service.</h3>
            <p>The risk map couldn&apos;t be loaded.</p>
            <button type="button" className="retry-btn" onClick={refetch}>Retry</button>
          </div>
        )}

        {data && data.features.length === 0 && (
          <div className="state-panel" style={{ margin: 24 }}>
            <h3>No monitored sites yet</h3>
            <p>The backend hasn&apos;t seeded any grid sites.</p>
          </div>
        )}

        {data && data.features.length > 0 && (
          <>
            <RiskMap featureCollection={data} onSelectSite={setSelected} />
            <RiskLegend />
            {selected && <SitePanel site={selected} onClose={() => setSelected(null)} />}
          </>
        )}
      </div>
    </div>
  )
}
