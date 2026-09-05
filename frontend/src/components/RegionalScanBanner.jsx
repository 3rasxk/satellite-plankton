import {
  formatRelativeTime,
  formatIndexValue,
  regionalIndexDomain,
  REGIONAL_INDEX_RAMP_HEX,
  REGIONAL_INDEX_LABEL,
  REGIONAL_PRIMARY_INDEX,
} from '../constants.js'

/**
 * Last-scanned/status banner for the regional bloom scan layer
 * (backend `GET /regional-scan`) -- reports on the regional-scan run
 * that RegionalScanLayer.jsx's pins/clusters belong to.
 *
 * Deliberately separate from the existing `map-date-pill` in
 * OverviewPage.jsx, which describes `/risk-map`'s 7-site data and is
 * left untouched. Per spec §7, the regional detection scan and the
 * unvalidated Ang Sila spatial-trend test "must never be blurred
 * together in the response or the frontend" -- this banner exists so
 * that when the regional-scan layer is visible, the map always shows
 * two clearly separate last-updated indicators for two different
 * datasets, rather than letting the risk-map's date pill imply it also
 * describes the regional-scan pins now on screen.
 *
 * Visual pattern: reuses `.validation-callout` (see ValidationPage.jsx)
 * for its box chrome -- a self-contained bordered/tinted callout that
 * already carries "here is a caveat the user must read" meaning
 * elsewhere in the dashboard. `.status-banner` (SatelliteImage.jsx) was
 * the other candidate named in the spec review, but it has no
 * standalone box styling of its own (global.css only gives it
 * `margin: 0` nested inside `.satellite-image-frame`; its visible box
 * comes entirely from that ambient parent) -- reusing it here would
 * mean inventing new border/background CSS from scratch, which is what
 * the spec explicitly says not to do. `.validation-callout` is
 * self-contained and only needs new position/size rules (see
 * `.regional-scan-banner` in global.css) to work as a map overlay,
 * positioned as an absolute sibling of `map-date-pill` / `RiskLegend` /
 * `MapControls` per spec §10. The status dot's colour reuses the
 * existing `--status-ok` / `--status-error` tokens and inline-style
 * convention already used for the service-status dots in
 * ReportsPage.jsx -- these tokens are documented in tokens.css as the
 * "system-health signal" pair, distinct from the --risk-* ramp, which
 * is exactly what a scan run's ok/error/partial_error status is.
 *
 * Also carries the regional-scan layer's own legend and interim notice.
 * RegionalScanLayer.jsx currently paints each pin by its primary spectral
 * index value on the neutral --regional-index-* ramp, because no point of
 * the latest run carries a `threshold_tier` (the anomaly cutoffs in
 * detection/src/config.yaml are uncalibrated). RiskLegend.jsx describes
 * the 7-site risk ramp and would be actively misleading if read as
 * describing these pins, so the index ramp gets its own legend here,
 * worded as an index value rather than a risk level. The interim notice
 * is rendered only while this run really did produce no tier and no
 * cluster -- it is checked against the response, not hard-coded.
 *
 * Renders nothing when no regional scan has ever completed
 * (`data.run` is null) -- same null-guard convention as
 * RegionalScanLayer.jsx's own `if (!data?.run) return null`. Every
 * value shown is read straight from the real API response; nothing
 * here is fabricated or placeholder text.
 */
const STATUS_LABEL_TH = {
  ok: 'สแกนสำเร็จ',
  partial_error: 'สแกนสำเร็จบางส่วน (มีข้อผิดพลาด)',
  error: 'สแกนล้มเหลว',
  running: 'กำลังสแกน',
}

export default function RegionalScanBanner({ data }) {
  if (!data?.run) return null

  const { run, caveat, disclaimer } = data
  const points = data.points || []
  const clusters = data.clusters || []
  // The interim notice is a claim about this run, so it is checked against
  // this run rather than hard-coded: it holds only while the scan produced
  // no threshold_tier and no cluster anywhere. The moment a point does
  // clear a cutoff, the layer is showing a detection again and this line
  // must not still say otherwise.
  const spatialTriggerIdle =
    clusters.length === 0 && points.every((p) => !p.threshold_tier)
  const domain = regionalIndexDomain(points)
  const primaryLabel = REGIONAL_INDEX_LABEL[REGIONAL_PRIMARY_INDEX]
  // completed_at is null while a scan is still running (or aborted before
  // finishing), so fall back to date_used -- never invent a timestamp.
  const lastScannedSource = run.completed_at || run.date_used
  const isErrorLike = run.status === 'error' || run.status === 'partial_error'
  const statusDotColor = isErrorLike ? 'var(--status-error)' : 'var(--status-ok)'

  return (
    <div className="regional-scan-banner validation-callout" role="status">
      <div className="regional-scan-banner-status-row">
        <span className="regional-scan-banner-dot" style={{ background: statusDotColor }} aria-hidden="true" />
        <span className="headline">
          สแกนภูมิภาค: {lastScannedSource ? formatRelativeTime(lastScannedSource) : 'ยังไม่เคยสแกน'}
        </span>
        <span className={`regional-scan-banner-status-text${isErrorLike ? ' is-error' : ''}`}>
          {STATUS_LABEL_TH[run.status] || run.status}
        </span>
      </div>
      {spatialTriggerIdle && (
        <p className="regional-scan-interim">index values only — no anomaly detection active</p>
      )}
      {domain && (
        <div className="regional-scan-index-legend">
          <span className="regional-scan-index-legend-title">
            {primaryLabel} index value — not a risk level
          </span>
          <div className="regional-scan-index-legend-ramp" aria-hidden="true">
            {REGIONAL_INDEX_RAMP_HEX.map((hex) => (
              <span key={hex} style={{ background: hex }} />
            ))}
          </div>
          <div className="regional-scan-index-legend-scale">
            <span>{formatIndexValue(domain.min)}</span>
            <span>{formatIndexValue(domain.max)}</span>
          </div>
          <span className="regional-scan-index-legend-note">
            shaded across this scan&apos;s own 5th–95th percentile · hollow grey ring = no satellite pass
          </span>
        </div>
      )}
      <p>{caveat}</p>
      <p>{disclaimer}</p>
    </div>
  )
}
