/**
 * Raster coverage view — its own page, not a toggle on the pin map.
 *
 * Shows continuous index readings across the whole study polygon, with
 * unmeasured water drawn as an explicit hatch rather than left blank.
 * Clicking anywhere on the raster reads that one cell back out of the
 * stored blob the picture was drawn from — the four index values and
 * that cell's own acquisition date. Not a live satellite call: the map
 * shows what was already measured, so a click must answer with the number
 * behind the pixel on screen and give the same answer every time.
 *
 * The scan banner (dates, coverage, the no-anomaly statement) is a later
 * piece; this page carries the map, the overlay, the legend and the
 * per-cell inspector.
 */
import { useCallback, useState } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRasterScan, getRasterPixel } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import RasterOverlay from '../components/RasterOverlay.jsx'
import RasterLegend from '../components/RasterLegend.jsx'
import RasterPixelProbe from '../components/RasterPixelProbe.jsx'
import RasterPixelPanel from '../components/RasterPixelPanel.jsx'

export default function RasterPage() {
  const { data, loading, error, refetch } = useApi(getRasterScan, [])
  const [picked, setPicked] = useState(null)

  // Only ask once there is a raster to ask about; without a rendered run
  // the endpoint has nothing to answer from and returns 404, and a 404
  // rendered as an error would read as "nothing found here".
  const hasRaster = Boolean(data?.run_id)
  const fetchPixel = useCallback(
    () => (picked ? getRasterPixel(picked.lat, picked.lng) : Promise.resolve(null)),
    [picked],
  )
  const {
    data: pixel,
    loading: pixelLoading,
    error: pixelError,
  } = useApi(fetchPixel, [picked], { enabled: Boolean(picked) && hasRaster })

  return (
    <div className="overview-page">
      <div className="overview-map-area">
        <RiskMap mode="true_color">
          <RasterOverlay data={data} />
          {hasRaster && <RasterPixelProbe onPick={setPicked} />}
        </RiskMap>

        {data?.legend && <RasterLegend legend={data.legend} />}

        <RasterPixelPanel
          pixel={pixel}
          loading={pixelLoading}
          error={pixelError}
          onClose={() => setPicked(null)}
        />

        <div className="raster-status info-callout glass" role="status">
          {loading && <p>กำลังโหลดภาพแรสเตอร์…</p>}
          {error && (
            <p>
              โหลดภาพแรสเตอร์ไม่สำเร็จ{' '}
              <button type="button" className="retry-btn" onClick={refetch}>ลองใหม่</button>
            </p>
          )}
          {!loading && !error && !data?.run_id && (
            <p>{data?.reason || 'ยังไม่มีภาพแรสเตอร์ — ต้องรันการสแกนก่อน'}</p>
          )}
          {data?.run_id && (
            <p>
              วันที่เป้าหมาย <span className="mono">{data.date_used}</span> · ภาพจาก{' '}
              <span className="mono">{data.oldest_scene_date}</span> ถึง{' '}
              <span className="mono">{data.newest_scene_date}</span> · ความละเอียด {data.scale_m} ม. ·
              คลิกบนแผนที่เพื่อดูค่าของเซลล์
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
