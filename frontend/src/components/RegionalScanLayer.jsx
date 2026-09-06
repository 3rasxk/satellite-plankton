import { useMemo } from 'react'
import { CircleMarker, Popup, Tooltip } from 'react-leaflet'
import {
  NO_DATA_HEX, NO_DATA_LINE_HEX, REGIONAL_PRIMARY_INDEX, REGIONAL_INDEX_LABEL,
  regionalIndexDomain, regionalIndexColor, formatIndexValue,
} from '../constants.js'

const EMPTY_POINTS = []
const POINT_STATUS = {
  ok: 'มีค่าอ่านดาวเทียม',
  no_data_yet: 'ยังไม่ได้สแกน',
  no_imagery: 'ไม่มีภาพที่ผ่านเกณฑ์เมฆในช่วงค้นหา',
  no_water_pixels: 'ไม่พบพิกเซลน้ำที่ใช้ได้ในจุดตัวอย่าง',
  no_climatology: 'ไม่มีข้อมูลฐาน MODIS — แสดงดัชนีที่อ่านได้',
  error: 'อ่านข้อมูลจุดนี้ไม่สำเร็จ',
}

function PointReadings({ point, targetDate }) {
  const ageDays = point.actual_date && targetDate
    ? Math.round((Date.parse(targetDate) - Date.parse(point.actual_date)) / 86400000)
    : null
  return (
    <div className="regional-point-readings">
      <strong>จุดกริด {point.point_id}</strong>
      <div className="mono">{point.lat.toFixed(4)}°N, {point.lng.toFixed(4)}°E</div>
      <div>{POINT_STATUS[point.status] || point.status}</div>
      <dl>
        {Object.entries(REGIONAL_INDEX_LABEL).map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd className="mono">{formatIndexValue(point.index_values?.[key])}</dd>
          </div>
        ))}
      </dl>
      <div>วันที่ภาพจริง: <span className="mono">{point.actual_date || 'ยังไม่มีวันที่ภาพ'}</span></div>
      {Number.isFinite(ageDays) && ageDays >= 0 && <div>ก่อนวันเป้าหมาย {ageDays} วัน</div>}
      <div>ค่าดัชนีเท่านั้น — ยังไม่มีการประเมินความผิดปกติ</div>
    </div>
  )
}

/** Every API point gets one pin, irrespective of status, threshold or cluster.
 * Missing readings stay null. Popup values and dates come from that cached
 * point; clicking does not silently fetch a different date's observation.
 */
export default function RegionalScanLayer({ data }) {
  const points = data?.points || EMPTY_POINTS
  const domain = useMemo(() => regionalIndexDomain(points), [points])
  const targetDate = data?.snapshot_date_used ?? data?.run?.date_used

  return points.map((point) => {
    const primary = point.index_values?.[REGIONAL_PRIMARY_INDEX]
    const hasPrimary = Number.isFinite(primary)
    return (
      <CircleMarker
        key={point.point_id}
        center={[point.lat, point.lng]}
        radius={hasPrimary ? 6 : 4}
        pathOptions={{
          color: hasPrimary ? '#ffffff' : NO_DATA_LINE_HEX,
          weight: 1,
          dashArray: hasPrimary ? undefined : '2,2',
          fillColor: hasPrimary ? regionalIndexColor(primary, domain) : NO_DATA_HEX,
          fillOpacity: hasPrimary ? 0.9 : 0.3,
          className: 'regional-scan-point',
        }}
        eventHandlers={{
          add: ({ target }) => {
            const element = target.getElement?.()
            if (!element) return
            element.setAttribute('tabindex', '0')
            element.setAttribute('role', 'button')
            // The same marker survives polling. Keep this label stable;
            // the popup renders the current status and readings reactively.
            element.setAttribute('aria-label', `จุดกริด ${point.point_id}: เปิดค่าดัชนี สถานะ และวันที่ภาพจริง`)
            element.addEventListener('keydown', (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                target.openPopup()
              }
            })
          },
        }}
      >
        <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
          <PointReadings point={point} targetDate={targetDate} />
        </Tooltip>
        <Popup><PointReadings point={point} targetDate={targetDate} /></Popup>
      </CircleMarker>
    )
  })
}
