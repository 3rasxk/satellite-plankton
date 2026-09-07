/**
 * Raster coverage view — its own page, not a toggle on the pin map.
 *
 * Shows continuous index readings across the whole study polygon, with
 * unmeasured water drawn as an explicit hatch rather than left blank.
 * The scan banner (dates, coverage, the no-anomaly statement) is a
 * later piece; this page currently carries the map, the overlay and the
 * legend.
 */
import { useApi } from '../hooks/useApi.js'
import { getRasterScan } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import RasterOverlay from '../components/RasterOverlay.jsx'
import RasterLegend from '../components/RasterLegend.jsx'

export default function RasterPage() {
  const { data, loading, error, refetch } = useApi(getRasterScan, [])

  return (
    <div className="overview-page">
      <div className="overview-map-area">
        <RiskMap mode="true_color">
          <RasterOverlay data={data} />
        </RiskMap>

        {data?.legend && <RasterLegend legend={data.legend} />}

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
              <span className="mono">{data.newest_scene_date}</span> · ความละเอียด {data.scale_m} ม.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
