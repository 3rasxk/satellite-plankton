import { formatRelativeTime } from '../constants.js'

/**
 * Last-scanned/status banner for the regional bloom scan layer
 * (backend `GET /regional-scan`) -- reports on the regional-scan run
 * that RegionalScanLayer.jsx's pins/clusters belong to.
 *
 * Deliberately separate from the existing `map-date-pill` in
 * OverviewPage.jsx, which describes `/risk-map`'s 6-site data and is
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
      <p>{caveat}</p>
      <p>{disclaimer}</p>
    </div>
  )
}
