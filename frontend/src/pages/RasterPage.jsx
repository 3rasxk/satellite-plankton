/**
 * Raster coverage view — its own page, not a toggle on the pin map.
 *
 * Shows valid index readings inside the study polygon; all unmeasured
 * pixels remain transparent over the Light Map.
 * Clicking anywhere on the raster reads that one cell back out of the
 * stored blob the picture was drawn from — the four index values and
 * that cell's own acquisition date. Not a live satellite call: the map
 * shows what was already measured, so a click must answer with the number
 * behind the pixel on screen and give the same answer every time.
 *
 * Four pieces, all reading the same `/raster-scan` run: the overlay, the
 * legend, the per-cell inspector, and `RasterScanBanner` — which states
 * in words what the picture is (dates and their per-day shares, how much
 * of the polygon carries a reading, what a cell actually samples, and
 * that no anomaly statistic exists). The banner replaced this page's
 * earlier inline status line, which showed only the target date, the
 * scene-date range and the scale.
 */
import { useCallback, useState } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRasterScan, getRasterPixel } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import RasterLayerSwitcher, { RasterMapLayers } from '../components/RasterLayerSwitcher.jsx'
import { RasterLegendDock } from '../components/RasterLegend.jsx'
import RasterPixelProbe from '../components/RasterPixelProbe.jsx'
import RasterPixelPanel from '../components/RasterPixelPanel.jsx'
import RasterScanBanner from '../components/RasterScanBanner.jsx'

export default function RasterPage() {
  const { data, loading, error, refetch } = useApi(getRasterScan, [])

  // A different scan replaces the picture and all inspector state in one
  // render. An old reading or pending response must not outlive its image.
  return (
    <RasterView
      key={data?.run_id ?? 'no-raster'}
      data={data}
      loading={loading}
      error={error}
      refetch={refetch}
    />
  )
}

function RasterView({ data, loading, error, refetch }) {
  const [picked, setPicked] = useState(null)
  const [layerMode, setLayerMode] = useState('ndci')
  const runId = data?.run_id

  // Only ask once there is a raster to ask about; without a rendered run
  // the endpoint has nothing to answer from and returns 404, and a 404
  // rendered as an error would read as "nothing found here".
  const hasRaster = Boolean(runId)
  const fetchPixel = useCallback(
    () => (picked ? getRasterPixel(picked.lat, picked.lng, runId) : Promise.resolve(null)),
    [picked, runId],
  )
  const {
    data: pixel,
    loading: pixelLoading,
    error: pixelError,
  } = useApi(fetchPixel, [picked], { enabled: Boolean(picked) && hasRaster })

  return (
    <div className="overview-page">
      <div className="overview-map-area">
        <RiskMap mode="raster">
          <RasterMapLayers mode={layerMode} data={data} />
          <RasterLayerSwitcher
            mode={layerMode}
            onModeChange={setLayerMode}
            trueColorAvailable={Boolean(data?.true_color_url)}
          />
          {hasRaster && <RasterPixelProbe onPick={setPicked} />}
        </RiskMap>

        <RasterLegendDock layerMode={layerMode} legend={data?.legend} hasRaster={hasRaster} />

        <RasterPixelPanel
          pixel={pixel}
          loading={pixelLoading}
          error={pixelError}
          onClose={() => setPicked(null)}
        />

        <RasterScanBanner data={data} loading={loading} error={error} onRefresh={refetch} />
      </div>
    </div>
  )
}
