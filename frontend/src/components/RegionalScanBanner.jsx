import {
  formatIndexValue, regionalIndexDomain, REGIONAL_INDEX_RAMP_HEX,
  REGIONAL_INDEX_LABEL, REGIONAL_PRIMARY_INDEX,
} from '../constants.js'

const STATUS_LABEL_TH = {
  ok: 'สแกนสำเร็จ',
  partial_error: 'บางจุดอ่านข้อมูลไม่สำเร็จ',
  error: 'สแกนล้มเหลว',
  running: 'กำลังสแกน — ผลและค่าที่อ่านได้จะอัปเดตเมื่อสแกนเสร็จ',
}

/** Counts come from the points actually shown, including unavailable readings.
 * The scan target date is labelled separately from each pin's scene date.
 */
export default function RegionalScanBanner({ data, loading, error, onRefresh }) {
  const points = data?.points || []
  const run = data?.run
  const withReadings = points.filter((point) =>
    Object.values(point.index_values || {}).some((value) => Number.isFinite(value)),
  ).length
  const pending = points.filter((point) => point.status === 'no_data_yet').length
  const domain = regionalIndexDomain(points)

  return (
    <div className="regional-scan-banner info-callout" role="status">
      <div className="regional-scan-banner-status-row">
        <span className="headline">จุดสแกนทั่วอ่าวไทยตอนบน</span>
        <button type="button" className="retry-btn" onClick={onRefresh} disabled={loading}>
          {loading ? 'กำลังโหลด…' : 'โหลดผลล่าสุด'}
        </button>
      </div>
      {error && <p>โหลดผลสแกนไม่สำเร็จ — กดโหลดผลล่าสุดเพื่อลองอีกครั้ง</p>}
      {data && (
        <>
          <p>
            แสดงทุกจุด {points.length} จุด · ระยะกริด {data.grid_spacing_km ?? run?.grid_spacing_km} กม.
            <br />
            มีค่าอ่าน {withReadings} · ยังไม่ได้สแกน {pending} · ไม่มีค่าอ่าน {points.length - withReadings - pending}
          </p>
          <p>{run ? STATUS_LABEL_TH[run.status] || run.status : 'ยังไม่มีผลสแกน — แสดงตำแหน่งกริดที่เตรียมไว้'}</p>
          {run?.status === 'running' && Number.isFinite(run.total_points) && (
            <p>รอบที่กำลังสแกนมี {run.total_points} จุด</p>
          )}
          {run?.date_used && <p>วันที่เป้าหมายการสแกน: <span className="mono">{run.date_used}</span></p>}
          {data.snapshot_date_used && data.snapshot_date_used !== run?.date_used && (
            <p>ข้อมูลที่แสดงมาจากรอบวันที่ <span className="mono">{data.snapshot_date_used}</span></p>
          )}
          {data.max_scene_age_days != null && (
            <p>ตั้งค่าการสแกน: ใช้ภาพล่าสุดที่ใช้ได้ ไม่เกิน {data.max_scene_age_days} วันก่อนวันเป้าหมาย · แต่ละจุดอาจใช้ภาพคนละวัน</p>
          )}
        </>
      )}
      <p className="regional-scan-interim">แสดงค่าดัชนีทุกจุด ไม่กรองด้วย threshold</p>
      <p>index values only — no anomaly detection active</p>
      {domain && (
        <div className="regional-scan-index-legend">
          <span className="regional-scan-index-legend-title">
            สีตามค่า {REGIONAL_INDEX_LABEL[REGIONAL_PRIMARY_INDEX]} ของจุดที่แสดง
          </span>
          <div className="regional-scan-index-legend-ramp" aria-hidden="true">
            {REGIONAL_INDEX_RAMP_HEX.map((hex) => <span key={hex} style={{ background: hex }} />)}
          </div>
          <div className="regional-scan-index-legend-scale">
            <span>{formatIndexValue(domain.min)}</span><span>{formatIndexValue(domain.max)}</span>
          </div>
          <span className="regional-scan-index-legend-note">ช่วงสีเปอร์เซ็นไทล์ 5–95 ของค่าอ่าน โดยยังแสดงจุดนอกช่วงทั้งหมด</span>
        </div>
      )}
      <p>วงเส้นประ = ไม่มีค่า NDCI · กดจุดเพื่อดูดัชนีทั้ง 4 ค่า สถานะ และวันที่ภาพจริง</p>
      {data?.disclaimer && <p className="regional-scan-index-legend-note">{data.disclaimer}</p>}
    </div>
  )
}
