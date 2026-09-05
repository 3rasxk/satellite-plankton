import { useMemo } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRiskMap } from '../api/client.js'
import Icon from '../components/Icon.jsx'
import {
  RISK_LABEL_TH,
  RISK_COLOR_VAR,
  NO_DATA_STATUS,
  STATUS_LABEL,
  formatRelativeTime,
  formatZ,
  ANOMALY_NOT_COMPUTED,
} from '../constants.js'

/**
 * Aquaculture Zones page (design spec Screen 3: "พื้นที่เพาะเลี้ยงสัตว์น้ำ").
 *
 * CLAUDE.md truth boundary: no actual aquaculture zone coordinates exist
 * in the system. This page maps representative Thai aquaculture zones to
 * their nearest monitored grid site as a proxy — the amber disclosure
 * banner makes this limitation explicit. Cell-density data ("ความหนาแน่น
 * เซลล์") is always "ไม่มีข้อมูล" — never fabricated.
 */

// Representative aquaculture zones mapped to nearest grid site proxy.
// Distances are approximate straight-line estimates.
const AQUACULTURE_ZONES = [
  {
    id: 'sriracha_bay',
    name: 'อ่าวศรีราชา',
    province: 'ชลบุรี',
    type: 'กุ้งขาว / หอยแมลงภู่',
    nearestSiteId: 'siracha',
    distanceKm: '~2',
  },
  {
    id: 'bangpakong',
    name: 'ปากแม่น้ำบางปะกง',
    province: 'ฉะเชิงเทรา',
    type: 'กุ้งขาว / ปลากะพง',
    nearestSiteId: 'chaophraya_mouth',
    distanceKm: '~25',
  },
  {
    id: 'thachin_estuary',
    name: 'ปากแม่น้ำท่าจีน',
    province: 'สมุทรสาคร',
    type: 'หอยแครง / กุ้ง',
    nearestSiteId: 'thachin_mouth',
    distanceKm: '~3',
  },
  {
    id: 'bangsaen_coast',
    name: 'ชายฝั่งบางแสน',
    province: 'ชลบุรี',
    type: 'หอยแมลงภู่ / สาหร่าย',
    nearestSiteId: 'bangsaen',
    distanceKm: '~1',
  },
]

export default function AquaculturePage() {
  const { data, loading, error, refetch } = useApi(getRiskMap, [])

  const siteMap = useMemo(() => {
    const map = {}
    if (data?.features) {
      for (const f of data.features) {
        map[f.properties.site_id] = {
          ...f.properties,
          lat: f.geometry.coordinates[1],
          lng: f.geometry.coordinates[0],
        }
      }
    }
    return map
  }, [data])

  return (
    <div className="page">
      <div className="page-header">
        <h1>พื้นที่เพาะเลี้ยงสัตว์น้ำ</h1>
        <span className="updated-line">
          พื้นที่เพาะเลี้ยงสัตว์น้ำที่อาจได้รับผลกระทบจากสาหร่ายพิษ · อ่าวไทยตอนบน
        </span>
      </div>

      {/* Amber disclosure banner */}
      <div className="aquaculture-disclosure">
        <div className="aquaculture-disclosure-icon" aria-hidden="true"><Icon name="alert" size={19} /></div>
        <div>
          <strong>ข้อจำกัดของข้อมูล</strong>
          <p>
            พิกัดที่แน่นอนของพื้นที่เพาะเลี้ยงสัตว์น้ำยังไม่ได้ถูกบันทึกในระบบ
            ข้อมูลที่แสดงเป็นค่าจากจุดตรวจวัดที่ใกล้ที่สุด (proxy) ไม่ใช่ค่าที่วัดจากพื้นที่เพาะเลี้ยงโดยตรง
          </p>
        </div>
      </div>

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
        <>
          {/* Zone cards */}
          <section className="summary-section">
            <div className="section-title">พื้นที่เพาะเลี้ยง</div>
            <div className="aquaculture-zone-grid">
              {AQUACULTURE_ZONES.map((zone) => {
                const proxySite = siteMap[zone.nearestSiteId]
                const isNoData = !proxySite || NO_DATA_STATUS.has(proxySite.status)
                const riskVar = proxySite ? RISK_COLOR_VAR[proxySite.risk_level] : null

                return (
                  <div key={zone.id} className="zone-card">
                    <div className="zone-card-header">
                      <h3 className="zone-card-name">{zone.name}</h3>
                      <span
                        className={`status-badge${isNoData ? ' no-data' : ''}`}
                      >
                        <span
                          className="dot"
                          style={
                            !isNoData && riskVar
                              ? { background: `var(${riskVar})` }
                              : undefined
                          }
                        />
                        {isNoData
                          ? 'ไม่มีค่าอ่าน'
                          : RISK_LABEL_TH[proxySite.risk_level] || 'ยังประเมินไม่ได้'}
                      </span>
                    </div>
                    <dl className="zone-card-details">
                      <dt>จังหวัด</dt>
                      <dd>{zone.province}</dd>
                      <dt>ประเภทการเลี้ยง</dt>
                      <dd>{zone.type}</dd>
                      <dt>จุดตรวจวัดใกล้สุด</dt>
                      <dd>{proxySite ? proxySite.name : '—'}</dd>
                      <dt>ระยะห่าง</dt>
                      <dd className="mono">{zone.distanceKm} กม.</dd>
                      <dt>Spatial anomaly z-score</dt>
                      <dd>
                        {proxySite?.spatial_anomaly_z == null ? ANOMALY_NOT_COMPUTED : formatZ(proxySite.spatial_anomaly_z)}
                      </dd>
                      <dt>ความหนาแน่นเซลล์</dt>
                      <dd className="no-data-text">ไม่มีข้อมูล</dd>
                    </dl>
                  </div>
                )
              })}
            </div>
          </section>

          {/* Real grid sites reference */}
          <section className="summary-section">
            <div className="section-title">จุดตรวจวัดจริงทั้ง {data.features.length} จุด</div>
            <div className="table-scroll">
              <table className="events-table">
                <thead>
                  <tr>
                    <th>จุดตรวจวัด</th>
                    <th>พิกัด</th>
                    <th>สถานะ</th>
                    <th>Spatial anomaly z</th>
                    <th>อัปเดต</th>
                  </tr>
                </thead>
                <tbody>
                  {data.features.map((f) => {
                    const p = f.properties
                    const isNoData = NO_DATA_STATUS.has(p.status)
                    const riskVar = RISK_COLOR_VAR[p.risk_level]

                    return (
                      <tr key={p.site_id}>
                        <td>{p.name}</td>
                        <td className="mono">
                          {f.geometry.coordinates[1].toFixed(4)}°N, {f.geometry.coordinates[0].toFixed(4)}°E
                        </td>
                        <td>
                          <span
                            className={`status-badge${isNoData ? ' no-data' : ''}`}
                          >
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
                        <td>{p.spatial_anomaly_z == null ? ANOMALY_NOT_COMPUTED : formatZ(p.spatial_anomaly_z)}</td>
                        <td className="mono table-date">
                          {p.fetched_at ? formatRelativeTime(p.fetched_at) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
