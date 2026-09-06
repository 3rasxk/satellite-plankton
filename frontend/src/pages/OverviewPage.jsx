import { useEffect, useState } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRiskMap, getRegionalScan } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import MapControls from '../components/MapControls.jsx'
import SitePanel from '../components/SitePanel.jsx'
import RegionalScanLayer from '../components/RegionalScanLayer.jsx'
import RegionalScanBanner from '../components/RegionalScanBanner.jsx'

/** The regional grid is the default map; named monitoring stations are optional.
 * Fetching the grid never depends on the seven-station endpoint succeeding.
 */
export default function OverviewPage() {
  const [mode, setMode] = useState('true_color')
  const [selectedSite, setSelectedSite] = useState(null)
  const [showMonitoringSites, setShowMonitoringSites] = useState(false)
  const sites = useApi(getRiskMap, [], { enabled: showMonitoringSites })
  const regional = useApi(getRegionalScan, [])
  const { refetch } = regional

  useEffect(() => {
    const interval = setInterval(refetch, 30000)
    return () => clearInterval(interval)
  }, [refetch])

  return (
    <div className="overview-page">
      <div className="overview-map-area">
        <RiskMap
          featureCollection={showMonitoringSites ? sites.data : null}
          fitPoints={regional.data?.points}
          mode={mode}
          onSelectSite={setSelectedSite}
        >
          <RegionalScanLayer data={regional.data} />
        </RiskMap>
        <MapControls mode={mode} onModeChange={setMode} />
        <div className="map-segmented-control glass regional-layer-controls">
          <button
            type="button"
            className={showMonitoringSites ? 'active' : ''}
            aria-pressed={showMonitoringSites}
            onClick={() => {
              setShowMonitoringSites((value) => !value)
              setSelectedSite(null)
            }}
          >
            จุดตรวจวัดประจำ 7 จุด
          </button>
          {showMonitoringSites && sites.loading && <span>กำลังโหลด…</span>}
          {showMonitoringSites && sites.error && (
            <button type="button" onClick={sites.refetch}>โหลดจุดประจำใหม่</button>
          )}
        </div>
        <RegionalScanBanner
          data={regional.data} loading={regional.loading} error={regional.error} onRefresh={refetch}
        />
        {selectedSite && <SitePanel site={selectedSite} onClose={() => setSelectedSite(null)} />}
      </div>
    </div>
  )
}
