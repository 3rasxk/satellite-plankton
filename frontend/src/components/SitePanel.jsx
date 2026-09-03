import { useCallback, useEffect, useRef } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getTimeseries, detect, getPinSatellitePreview } from '../api/client.js'
import SatelliteImage from './SatelliteImage.jsx'
import TimeSeriesChart from './TimeSeriesChart.jsx'
import AnomalyStrip from './AnomalyStrip.jsx'
import { segmentsFromTimeseries } from '../utils/series.js'
import {
  RISK_LABEL,
  RISK_LABEL_TH,
  RISK_COLOR_VAR,
  NO_DATA_STATUS,
  STATUS_EXPLAINER_TH,
  RULE_DESCRIPTION_TH,
  formatSiteName,
  formatThaiDate,
} from '../constants.js'

// '—' for any value with no real source -- never a fabricated number.
// CLAUDE.md's truth boundary: absence of data is reported as absence,
// not filled in from a formula.
function fmtOrDash(value, digits = 2) {
  return value === null || value === undefined ? '—' : Number(value).toFixed(digits)
}

const today = () => new Date().toISOString().slice(0, 10)

/**
 * Site Detail Panel: Spectral Index metrics, the rule-based risk
 * assessment (risk_level()/config.yaml — no trained model anywhere in
 * this pipeline, CLAUDE.md §0/§1), the anomaly-z gauge, and the 90-day
 * Anomaly Strip. Every displayed value is real or '—', never derived
 * from a formula standing in for a missing source.
 */
export default function SitePanel({ site, onClose }) {
  const closeBtnRef = useRef(null)

  useEffect(() => {
    closeBtnRef.current?.focus()
  }, [site])

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const fetchTimeseries = useCallback(() => getTimeseries(site.lat, site.lng), [site.lat, site.lng])
  const fetchDetect = useCallback(() => detect(site.lat, site.lng, today()), [site.lat, site.lng])
  const fetchSatellitePreview = useCallback(
    () => getPinSatellitePreview(site.lat, site.lng, site.actual_date || today()),
    [site.lat, site.lng, site.actual_date],
  )

  const ts = useApi(fetchTimeseries, [site.lat, site.lng])
  const dt = useApi(fetchDetect, [site.lat, site.lng])
  const satPreview = useApi(fetchSatellitePreview, [site.lat, site.lng, site.actual_date])

  const riskColorVar = RISK_COLOR_VAR[site.risk_level] || null
  const isNoData = NO_DATA_STATUS.has(site.status)

  const trueColorImageUrl =
    site.true_color_image_url ||
    satPreview.data?.rgb_url ||
    dt.data?.true_color_image_url ||
    null

  const ndciHeatmapImageUrl =
    site.ndci_heatmap_image_url ||
    satPreview.data?.ndci_url ||
    dt.data?.ndci_heatmap_image_url ||
    null

  const sceneDate =
    satPreview.data?.acquisition_date ||
    dt.data?.actual_date ||
    site.actual_date ||
    today()

  // Card 1 (Spectral Index) -- every value is real or '—', never a
  // fabricated number derived from lat/lng or another index (CLAUDE.md's
  // truth boundary: absence of data is reported as absence).
  const latestPoint = ts.data?.points?.length ? ts.data.points[ts.data.points.length - 1] : null
  const chlorVal = latestPoint?.chlor_a ?? null
  const ndciVal = site.index_values?.['ndci'] ?? dt.data?.index_values?.['ndci'] ?? null
  const bda2Val = site.index_values?.['2bda'] ?? dt.data?.index_values?.['2bda'] ?? null
  const bda3Val = site.index_values?.['3bda'] ?? dt.data?.index_values?.['3bda'] ?? null
  // No API field currently surfaces SST or 7-day rainfall to the frontend
  // (risk_level()'s sst_anomaly/rainfall are computed server-side but not
  // exposed on RiskMapProperties or DetectResponse) -- always '—' until
  // a real endpoint provides them, never a formula standing in for one.
  const sstVal = null
  const rainfall7d = null
  const anomalyZ = site.anomaly_z ?? dt.data?.anomaly_z ?? null

  // Card 2 -- the real, rule-based escalation this project actually runs
  // (detection/src/prediction.py's risk_level(), CLAUDE.md §0/§1: rule-based
  // only, no trained model). `confidence_label` always carries its own
  // "indicative, not a validated forecast" caveat from config.yaml -- see
  // backend/src/schemas.py RiskMapProperties.confidence_label.
  const riskLevel = site.risk_level || 'normal'
  const triggeredRules = site.triggered_rules || []
  const confidenceLabel = site.confidence_label || null

  // Gauge meter (z from -2.0 to +3.0) -- only renders when a real
  // anomaly_z exists; null must not render as "0.0 / normal".
  const gaugePercent =
    anomalyZ == null ? null : Math.min(100, Math.max(0, ((anomalyZ - -2.0) / (3.0 - -2.0)) * 100))

  // Fast path (scheduler-cached) resolves instantly; the live fallbacks
  // (dt/satPreview) make real GEE calls that take several seconds -- while
  // they're in flight and no cached URL exists yet, show a loading state
  // rather than flashing "no image" and then replacing it once they
  // resolve (misleading, and slow-feeling for no reason beyond the UI
  // not saying what's actually happening).
  const imageResolving = !trueColorImageUrl && !ndciHeatmapImageUrl && (dt.loading || satPreview.loading)

  let noImageMessage = null
  if (!trueColorImageUrl && !ndciHeatmapImageUrl && !imageResolving) {
    noImageMessage = isNoData
      ? STATUS_EXPLAINER_TH[site.status] || 'ยังไม่มีภาพถ่ายดาวเทียมสำหรับจุดนี้'
      : 'ไม่มีข้อมูลภาพถ่ายดาวเทียมที่ใช้งานได้สำหรับพิกัดนี้'
  }

  return (
    <aside className="site-panel modern-panel" aria-label={`รายละเอียดจุดตรวจวัด ${formatSiteName(site)}`}>
      {/* Header */}
      <div className="site-panel-header">
        <div className="site-panel-header-info">
          <div className="site-name">{formatSiteName(site)}</div>
          <div className="site-coords mono">
            {site.lat.toFixed(4)}°N, {site.lng.toFixed(4)}°E
          </div>
          <div className="header-risk-inline">
            <span className={`risk-pill${isNoData ? ' no-data' : ''}`}>
              <span
                className="dot"
                style={riskColorVar && !isNoData ? { background: `var(${riskColorVar})` } : undefined}
              />
              {isNoData ? 'ไม่มีค่าอ่าน' : RISK_LABEL_TH[site.risk_level] || RISK_LABEL[site.risk_level] || site.risk_level}
            </span>
          </div>
        </div>
        <button
          ref={closeBtnRef}
          type="button"
          className="site-panel-close"
          onClick={onClose}
          aria-label="ปิดหน้ารายละเอียด"
        >
          ×
        </button>
      </div>

      <div className="panel-content-cards">
        {/* --- Card 1: Spectral Index --- */}
        <div className="detail-card">
          <div className="detail-card-header">
            <span className="detail-card-title">Spectral Index</span>
          </div>
          <div className="metric-grid-2x2">
            <div className="metric-grid-cell">
              <div className="metric-number mono">{fmtOrDash(chlorVal)}</div>
              <div className="metric-label-text">Chlorophyll-a mg/m³</div>
            </div>
            <div className="metric-grid-cell">
              <div className="metric-number mono">{fmtOrDash(ndciVal)}</div>
              <div className="metric-label-text">
                NDCI (20 m) <span className="approx-tag mono">APPROX</span>
              </div>
            </div>
            <div className="metric-grid-cell">
              <div className="metric-number mono">{fmtOrDash(bda2Val)}</div>
              <div className="metric-label-text">2BDB</div>
            </div>
            <div className="metric-grid-cell">
              <div className="metric-number mono">{fmtOrDash(bda3Val)}</div>
              <div className="metric-label-text">3BDB</div>
            </div>
            <div className="metric-grid-cell">
              <div className="metric-number mono">{fmtOrDash(sstVal, 1)}</div>
              <div className="metric-label-text">อุณหภูมิผิวน้ำ °C</div>
            </div>
            <div className="metric-grid-cell">
              <div className="metric-number mono">{fmtOrDash(rainfall7d, 1)}</div>
              <div className="metric-label-text">ฝนสะสม 7 วัน mm</div>
            </div>
          </div>
          <div className="detail-card-bottom-footer mono">
            <span>Sentinel-2 L2A · ฉาก {formatThaiDate(sceneDate) || sceneDate}</span>
          </div>
        </div>

        {/* --- Card 2: การประเมินความเสี่ยง (rule-based) & Anomaly Gauge ---
            Real risk_level()/config.yaml output only -- no ML model runs
            anywhere in this pipeline (CLAUDE.md §0/§1, locked decision:
            physics-based, not ML). confidence_label always carries its
            own "indicative, not a validated forecast" caveat -- never
            shown without it. */}
        <div className="detail-card risk-gauge-card">
          <div className="detail-card-header flex-between">
            <span className="detail-card-title">การประเมินความเสี่ยง</span>
            <span className="ai-ensemble-tag mono">Rule-based</span>
          </div>

          <div className="ai-prediction-hero">
            <div className="ai-prediction-main">
              <span className="ai-percentage-number mono">
                {RISK_LABEL_TH[riskLevel] || RISK_LABEL[riskLevel] || riskLevel}
              </span>
              <span className="ai-percentage-label">
                {confidenceLabel || 'ไม่มีข้อมูลระดับความเชื่อมั่น'}
              </span>
            </div>
          </div>

          {triggeredRules.length > 0 && (
            <div className="ai-forecast-arrival-box">
              <div className="arrival-title-row">
                <span className="arrival-caption">เงื่อนไขที่ตรงตามเกณฑ์</span>
              </div>
              <ul style={{ margin: '4px 0 0', paddingLeft: '18px', fontSize: '12.5px' }}>
                {triggeredRules.map((level) => (
                  <li key={level}>{RULE_DESCRIPTION_TH[level] || level}</li>
                ))}
              </ul>
            </div>
          )}

          {gaugePercent !== null ? (
            <>
              <div className="gauge-track-container">
                <div className="gauge-pointer-marker" style={{ left: `${gaugePercent}%` }}>
                  <span className="gauge-pointer-tag">
                    {anomalyZ > 0 ? `+${Number(anomalyZ).toFixed(2)}` : Number(anomalyZ).toFixed(2)}
                  </span>
                  <div className="gauge-pointer-pin" />
                </div>
                <div className="gauge-track-bar" />
              </div>

              <div className="gauge-threshold-ticks">
                <span>ปกติ (&lt; 1.5)</span>
                <span>เริ่มผิดปกติ (≥ 1.5)</span>
                <span>เตือนภัย (≥ 2.0)</span>
              </div>

              <div className="gauge-context-row">
                <span
                  className="gauge-status-dot"
                  style={{
                    background:
                      anomalyZ >= 2.0
                        ? 'var(--risk-warning)'
                        : anomalyZ >= 1.5
                          ? 'var(--risk-elevated)'
                          : 'var(--risk-normal)',
                  }}
                />
                <span className="gauge-context-note">
                  {anomalyZ >= 2.0
                    ? 'ค่าความผิดปกติสูงกว่าเกณฑ์เฉลี่ยมาก'
                    : anomalyZ >= 1.5
                      ? 'ค่าความผิดปกติสูงกว่าเกณฑ์เฉลี่ย'
                      : 'ค่าคลอโรฟิลล์อยู่ในเกณฑ์ปกติของฤดูกาล'}
                </span>
              </div>
            </>
          ) : (
            <p className="no-rules">ยังไม่มีค่า anomaly_z สำหรับจุดนี้</p>
          )}
        </div>

        {/* --- Card 3: Chlorophyll trends & 90-day Anomaly Strip --- */}
        <div className="detail-card">
          <div className="detail-card-header flex-between">
            <span className="detail-card-title">Chlorophyll trends</span>
            <span className="detail-card-date-range">ม.ค. — ส.ค.</span>
          </div>
          <div className="chart-legend-pills">
            <span className="chart-legend-pill">
              <span className="legend-line-sample current-line" /> ปี 2026
            </span>
            <span className="chart-legend-pill">
              <span className="legend-line-sample baseline-line" /> ค่าฐาน 20 ปี
            </span>
          </div>
          <TimeSeriesChart points={ts.data?.points || []} />

          {/* 90-day Anomaly Heat Strip */}
          <div style={{ marginTop: '8px', paddingTop: '10px', borderTop: '1px solid rgba(0,0,0,0.06)' }}>
            <div style={{ fontSize: '11px', fontWeight: 600, color: '#6e6e73', marginBottom: '6px' }}>
              ความผิดปกติย้อนหลัง 90 วัน (Daily Anomaly Strip)
            </div>
            <AnomalyStrip
              segments={segmentsFromTimeseries(ts.data?.points, 90)}
              leftLabel="90 วันก่อน"
              rightLabel="ล่าสุด"
              caption="สีของแถบ = ระดับความผิดปกติรายวันเทียบกับค่าเฉลี่ยตามฤดูกาล"
            />
          </div>
        </div>

        {/* --- Card 4: ภาพถ่ายดาวเทียม (Satellite Image Preview) --- */}
        <SatelliteImage
          trueColorUrl={trueColorImageUrl}
          ndciHeatmapUrl={ndciHeatmapImageUrl}
          noImageMessage={noImageMessage}
          sceneDate={sceneDate}
          resolving={imageResolving}
        />
      </div>
    </aside>
  )
}
