import { useCallback, useMemo } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRiskMap, getTimeseries } from '../api/client.js'
import StatCard from '../components/StatCard.jsx'
import AnomalyStrip from '../components/AnomalyStrip.jsx'
import {
  RISK_LABEL_TH,
  RISK_COLOR_VAR,
  NO_DATA_STATUS,
  formatZ,
  formatRelativeTime,
} from '../constants.js'
import { segmentsFromTimeseries } from '../utils/series.js'

/**
 * Seasonal Anomaly page (design spec Screen 2: "ความผิดปกติตามฤดูกาล").
 * Shows per-site anomaly strips (45 cells = 90 days / 2-day bins) and
 * stat cards for the region. Data from /risk-map (current snapshot) +
 * per-site /timeseries (90-day history).
 *
 * All z-scores are real MODIS-climatology-derived values — never
 * fabricated. No-data states rendered as hatched cells and dashes.
 */
export default function AnomalyPage() {
  const riskMapApi = useApi(getRiskMap, [])

  const sites = useMemo(
    () =>
      (riskMapApi.data?.features || []).map((f) => ({
        site_id: f.properties.site_id,
        name: f.properties.name,
        lat: f.geometry.coordinates[1],
        lng: f.geometry.coordinates[0],
        anomaly_z: f.properties.anomaly_z,
        status: f.properties.status,
        risk_level: f.properties.risk_level,
        fetched_at: f.properties.fetched_at,
      })),
    [riskMapApi.data],
  )

  const siteKey = sites.map((s) => s.site_id).join(',')

  const fetchAllTimeseries = useCallback(async () => {
    const results = await Promise.all(
      sites.map(async (site) => {
        try {
          const ts = await getTimeseries(site.lat, site.lng)
          return { site, points: (ts.points || []).slice(-90) }
        } catch {
          return { site, points: [] }
        }
      }),
    )
    return results
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteKey])

  const trendApi = useApi(fetchAllTimeseries, [siteKey], { enabled: sites.length > 0 })

  // Stat card values
  const totalSites = sites.length
  const sitesWithReadings = sites.filter((s) => !NO_DATA_STATUS.has(s.status)).length
  const sitesAtWatch = sites.filter(
    (s) => s.risk_level === 'watch' || s.risk_level === 'warning',
  ).length
  const maxZ = sites.reduce((max, s) => {
    if (s.anomaly_z != null && (max === null || s.anomaly_z > max)) return s.anomaly_z
    return max
  }, null)

  const newestFetch = useMemo(() => {
    const times = sites.map((s) => s.fetched_at).filter(Boolean).sort()
    return times.length ? times[times.length - 1] : null
  }, [sites])

  return (
    <div className="page">
      <div className="page-header">
        <h1>ความผิดปกติตามฤดูกาล</h1>
        <span className="updated-line">
          เปรียบเทียบค่าคลอโรฟิลล์ปัจจุบันกับค่าเฉลี่ยรายฤดูกาลจาก MODIS climatology (2002–ปัจจุบัน)
          · หน้าต่าง 90 วัน
          {newestFetch ? ` · อัปเดต ${formatRelativeTime(newestFetch)}` : ''}
        </span>
      </div>

      {riskMapApi.loading && (
        <div className="state-panel">
          <h3>กำลังโหลดข้อมูล…</h3>
        </div>
      )}

      {riskMapApi.error && (
        <div className="state-panel error">
          <h3>ไม่สามารถเชื่อมต่อบริการข้อมูลได้</h3>
          <button type="button" className="retry-btn" onClick={riskMapApi.refetch}>
            ลองอีกครั้ง
          </button>
        </div>
      )}

      {sites.length > 0 && (
        <>
          {/* Stat cards */}
          <section className="summary-section">
            <div className="stat-row anomaly-stat-row">
              <StatCard label="จุดตรวจวัด" value={totalSites} />
              <StatCard label="มีค่าอ่าน" value={sitesWithReadings} />
              <StatCard
                label="เฝ้าระวัง"
                value={sitesAtWatch}
                riskLevel={sitesAtWatch > 0 ? 'watch' : undefined}
              />
              <StatCard
                label="z-score สูงสุด"
                value={maxZ != null ? formatZ(maxZ) : '—'}
                detail="ค่าเบี่ยงเบนสูงสุดจากค่าเฉลี่ยรายฤดูกาล"
              />
            </div>
          </section>

          {/* Per-site anomaly strips */}
          <section className="summary-section">
            <div className="section-title">สัญญาณผิดปกติรายจุด · 90 วัน</div>

            {trendApi.loading && <p className="no-rules">กำลังโหลดข้อมูลรายจุด…</p>}
            {trendApi.error && (
              <div className="state-panel error">
                <h3>ไม่สามารถโหลดข้อมูลรายจุดได้</h3>
                <button type="button" className="retry-btn" onClick={trendApi.refetch}>
                  ลองอีกครั้ง
                </button>
              </div>
            )}

            {trendApi.data && (
              <div className="anomaly-site-rows">
                {trendApi.data.map(({ site, points }) => {
                  const isNoData = NO_DATA_STATUS.has(site.status)
                  const riskVar = RISK_COLOR_VAR[site.risk_level]
                  const segments = segmentsFromTimeseries(points, 90)

                  return (
                    <div key={site.site_id} className="anomaly-site-row">
                      <div className="anomaly-site-info">
                        <div className="anomaly-site-name">{site.name}</div>
                        <div className="anomaly-site-meta">
                          <span
                            className={`status-badge inline${isNoData ? ' no-data' : ''}`}
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
                              : RISK_LABEL_TH[site.risk_level] || site.risk_level}
                          </span>
                          <span className="mono anomaly-z-value">
                            z = {formatZ(site.anomaly_z)}
                          </span>
                        </div>
                      </div>
                      <div className="anomaly-site-strip">
                        <AnomalyStrip
                          segments={segments}
                          leftLabel="90 วันก่อน"
                          rightLabel="ล่าสุด"
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
