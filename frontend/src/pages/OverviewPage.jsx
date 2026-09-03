import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRiskMap, getRegionalScan } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import RiskLegend from '../components/RiskLegend.jsx'
import MapControls from '../components/MapControls.jsx'
import SitePanel from '../components/SitePanel.jsx'
import { MapOverlaySkeleton } from '../components/SkeletonLoader.jsx'
import { formatThaiDate } from '../constants.js'
import Icon from '../components/Icon.jsx'
import RegionalScanLayer from '../components/RegionalScanLayer.jsx'
import RegionalScanBanner from '../components/RegionalScanBanner.jsx'

export default function OverviewPage() {
  const { data, loading, error, refetch } = useApi(getRiskMap, [])
  const [mode, setMode] = useState('true_color')
  const [selectedSite, setSelectedSite] = useState(null)
  const [showRegionalScan, setShowRegionalScan] = useState(false)
  const { data: regionalScanData } = useApi(getRegionalScan, [], { enabled: showRegionalScan })

  const newestSceneDate = useMemo(() => {
    if (!data) return null
    const dates = data.features.map((f) => f.properties.actual_date).filter(Boolean).sort()
    return dates.length ? dates[dates.length - 1] : new Date().toISOString().slice(0, 10)
  }, [data])

  return (
    <div className="overview-page">
      <div className="overview-map-area">
        {loading && !data && <MapOverlaySkeleton />}
        {error && !data && (
          <div className="state-panel error" style={{ margin: 24 }}>
            <h3>Couldn&apos;t reach the data service.</h3>
            <button type="button" className="retry-btn" onClick={refetch}>Retry</button>
          </div>
        )}
        {data && data.features.length > 0 && (
          <>
            <RiskMap
              featureCollection={data}
              mode={mode}
              onSelectSite={setSelectedSite}
            >
              {showRegionalScan && <RegionalScanLayer data={regionalScanData} />}
            </RiskMap>
            <MapControls mode={mode} onModeChange={setMode} />
            <button
              type="button"
              className="map-segmented-control glass"
              style={{ position: 'absolute', top: 76, left: 16, zIndex: 500 }}
              onClick={() => setShowRegionalScan((v) => !v)}
              aria-pressed={showRegionalScan}
            >
              {showRegionalScan ? 'Hide regional scan' : 'Show regional scan'}
            </button>
            {showRegionalScan && <RegionalScanBanner data={regionalScanData} />}
            <RiskLegend mode={mode} />
            {selectedSite && (
              <SitePanel site={selectedSite} onClose={() => setSelectedSite(null)} />
            )}
            <div
              className="map-date-pill glass"
              title={`ข้อมูลภาพถ่ายดาวเทียม Sentinel-2: ${newestSceneDate || ''}`}
            >
              {loading ? (
                <span className="sync-spin-icon" title="กำลังอัปเดตข้อมูล...">
                  <Icon name="refresh" size={14} />
                </span>
              ) : (
                <Icon name="calendar" size={15} />
              )}
              <span>{newestSceneDate ? formatThaiDate(newestSceneDate) : '28 ส.ค. 2026'}</span>
              <Icon name="chevronDown" size={14} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
