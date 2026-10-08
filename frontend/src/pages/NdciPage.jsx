import { useApi } from '../hooks/useApi.js'
import { getRiskMap } from '../api/client.js'
import {
  RISK_LABEL_TH,
  RISK_COLOR_VAR,
  NO_DATA_STATUS,
  STATUS_LABEL,
  formatRelativeTime,
  formatZ,
  ANOMALY_NOT_COMPUTED,
  SIGNAL_ANOMALY_LABEL_TH,
  SIGNAL_ANOMALY_LEVEL_TH,
  SIGNAL_ANOMALY_NO_ASSESSMENT_TH,
} from '../constants.js'

/**
 * Sentinel-2 NDCI page (design spec Screen 1). Static educational content
 * about the 4 spectral indices used by the detection pipeline, plus a live
 * table showing the most-recent index reading per monitored grid site.
 *
 * Index formulas are the verbatim expressions from detection/src/config.yaml
 * — never a claim about precision or accuracy, just what formula was applied.
 * The table reads from /risk-map (same as the overview page) so it shows
 * the cached scheduler reading, not a live GEE call.
 */

const INDEX_CARDS = [
  {
    id: 'ndci',
    name: 'NDCI',
    fullName: 'Normalized Difference Chlorophyll Index',
    formula: '(B5 − B4) / (B5 + B4)',
    description:
      'ดัชนีสเปกตรัมจากแบนด์ Red Edge (B5) และ Red (B4) ของ Sentinel-2 — โครงการยังไม่มีสมการสอบเทียบเป็นความเข้มข้นคลอโรฟิลล์หรือระดับความเสี่ยง',
  },
  {
    id: '2bda',
    name: '2BDA',
    fullName: 'Two-Band Difference Algorithm',
    formula: 'B5 / B4',
    description:
      'อัตราส่วน Red Edge ต่อ Red — เป็นการแปลงจากอัตราส่วน B5/B4 ชุดเดียวกับ NDCI จึงไม่ใช่หลักฐานยืนยันอิสระ',
  },
  {
    id: '3bda',
    name: '3BDA',
    fullName: 'Three-Band Difference Algorithm',
    formula: '(1/B4 − 1/B5) × B6',
    description:
      'อัลกอริทึมสามแบนด์ — ลดอิทธิพลจากการกระเจิงย้อนกลับ (backscattering) เพื่อแยกสัญญาณคลอโรฟิลล์ได้ชัดขึ้น',
  },
  {
    id: 'b2b3',
    name: 'B2/B3',
    fullName: 'Exploratory Blue–Green Ratio',
    formula: 'B2 / B3',
    description:
      'อัตราส่วนแบนด์ Blue ต่อ Green สำหรับบริบทเชิงสำรวจ — ยังไม่ได้สอบเทียบหรือยืนยันว่าใช้จำแนก Noctiluca ได้',
  },
]

export default function NdciPage() {
  const { data, loading, error, refetch } = useApi(getRiskMap, [])

  const features = data?.features || []

  return (
    <div className="page">
      <div className="page-header">
        <h1>Sentinel-2 NDCI</h1>
        <span className="updated-line">
          ดัชนีสเปกตรัมที่ใช้ตรวจจับสัญญาณคลอโรฟิลล์จากภาพถ่ายดาวเทียม Sentinel-2 ความละเอียด 10–20 เมตร
        </span>
      </div>

      {/* Index definition cards */}
      <section className="ndci-index-grid">
        {INDEX_CARDS.map((idx) => (
          <div key={idx.id} className="index-def-card">
            <div className="index-def-header">
              <span className="index-def-name">{idx.name}</span>
              <span className="index-def-fullname">{idx.fullName}</span>
            </div>
            <div className="index-def-formula mono">{idx.formula}</div>
            <p className="index-def-desc">{idx.description}</p>
          </div>
        ))}
      </section>

      {/* Latest readings table */}
      <section className="summary-section">
        <div className="section-title">ค่าอ่านล่าสุดต่อจุดตรวจวัด</div>

        {loading && (
          <div className="state-panel">
            <h3>กำลังโหลดข้อมูล…</h3>
          </div>
        )}

        {error && (
          <div className="state-panel error">
            <h3>ไม่สามารถเชื่อมต่อบริการข้อมูลได้</h3>
            <button type="button" className="retry-btn" onClick={refetch}>
              ลองอีกครั้ง
            </button>
          </div>
        )}

        {data && (
          <div className="table-scroll">
            <table className="events-table ndci-table">
              <thead>
                <tr>
                  <th>จุดตรวจวัด</th>
                  <th>ดัชนีที่ใช้</th>
                  <th>NDCI</th>
                  <th>{SIGNAL_ANOMALY_LABEL_TH}</th>
                  <th>สถานะ</th>
                  <th>อัปเดต</th>
                </tr>
              </thead>
              <tbody>
                {features.map((f) => {
                  const p = f.properties
                  const isNoData = NO_DATA_STATUS.has(p.status)
                  const riskVar = RISK_COLOR_VAR[p.risk_level]

                  return (
                    <tr key={p.site_id}>
                      <td>
                        <div className="ndci-site-name">{p.name}</div>
                        <div className="ndci-site-coords mono">
                          {f.geometry.coordinates[1].toFixed(4)}°N, {f.geometry.coordinates[0].toFixed(4)}°E
                        </div>
                      </td>
                      <td className="mono">{isNoData ? '—' : p.index_used || 'NDCI'}</td>
                      <td className="mono">
                        {isNoData
                          ? '—'
                          : p.index_values?.ndci != null
                            ? p.index_values.ndci.toFixed(4)
                            : '—'}
                      </td>
                      <td>
                        {SIGNAL_ANOMALY_LEVEL_TH[p.signal_anomaly_level]
                          || SIGNAL_ANOMALY_NO_ASSESSMENT_TH}
                        <div className="table-subtext">
                          {p.spatial_anomaly_z == null
                            ? ANOMALY_NOT_COMPUTED
                            : `robust z = ${formatZ(p.spatial_anomaly_z)}`}
                        </div>
                      </td>
                      <td>
                        <span className={`status-badge${isNoData ? ' no-data' : ''}`}>
                          <span
                            className="dot"
                            style={
                              !isNoData && riskVar
                                ? { background: `var(${riskVar})` }
                                : undefined
                            }
                          />
                          {isNoData
                            ? STATUS_LABEL[p.status] || 'ไม่มีค่าอ่าน'
                            : RISK_LABEL_TH[p.risk_level] || 'ยังประเมินไม่ได้'}
                        </span>
                      </td>
                      <td className="mono table-date">
                        {p.fetched_at ? formatRelativeTime(p.fetched_at) : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
