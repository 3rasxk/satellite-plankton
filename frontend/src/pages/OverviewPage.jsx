import { useEffect, useState } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRegionalScan } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import MapControls from '../components/MapControls.jsx'
import RegionalScanLayer from '../components/RegionalScanLayer.jsx'
import RegionalScanBanner from '../components/RegionalScanBanner.jsx'

/** Only the regional sampling grid is shown on this map. */
export default function OverviewPage() {
  const [mode, setMode] = useState('true_color')
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
          fitPoints={regional.data?.points}
          mode={mode}
        >
          <RegionalScanLayer data={regional.data} />
        </RiskMap>
        <MapControls mode={mode} onModeChange={setMode} />
        <RegionalScanBanner
          data={regional.data} loading={regional.loading} error={regional.error} onRefresh={refetch}
        />
      </div>
    </div>
  )
}
