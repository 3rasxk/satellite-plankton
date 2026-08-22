import { useCallback, useEffect, useRef } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getTimeseries, detect } from '../api/client.js'
import AnomalyStrip from './AnomalyStrip.jsx'
import SatelliteImage from './SatelliteImage.jsx'
import { segmentsFromTimeseries } from '../utils/series.js'
import TimeSeriesChart from './TimeSeriesChart.jsx'
import {
  RISK_LABEL,
  RISK_COLOR_VAR,
  RULE_DESCRIPTION,
  NO_DATA_STATUS,
  STATUS_LABEL,
  STATUS_EXPLAINER,
  formatZ,
  formatConfidence,
} from '../constants.js'

const today = () => new Date().toISOString().slice(0, 10)

/**
 * Click-to-chart panel (docs/FRONTEND_PLAN.md §5). `site` is the clicked
 * risk-map feature's flattened {lat, lng, ...properties}. Fetches its own
 * /timeseries and /detect data independently of the map cell's cached
 * risk_level — the panel's "detection" block is deliberately a *separate*
 * fetch/claim from the map's risk_level/triggered_rules pill above it
 * (CLAUDE.md: detection and prediction are separate claims).
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

  const ts = useApi(fetchTimeseries, [site.lat, site.lng])
  const dt = useApi(fetchDetect, [site.lat, site.lng])

  const riskColorVar = RISK_COLOR_VAR[site.risk_level] || null
  const isNoData = NO_DATA_STATUS.has(site.status)

  // Image source: when the panel was opened from a map marker, `site`
  // carries `site_id` plus the scheduler's already-cached image URLs
  // (fast — a DB blob read, no live GEE call). Prefer those. Only fall
  // back to /detect's live (multi-second) render when there's no known
  // site_id to have a cache for in the first place (e.g. a future
  // arbitrary-point click that isn't one of the 6 monitored sites).
  const usingCachedImage = !!site.site_id
  const cachedTrueColor = usingCachedImage ? site.true_color_image_url || null : null
  const cachedNdci = usingCachedImage ? site.ndci_heatmap_image_url || null : null

  const liveTrueColor = !usingCachedImage ? dt.data?.true_color_image_url || null : null
  const liveNdci = !usingCachedImage ? dt.data?.ndci_heatmap_image_url || null : null

  const trueColorImageUrl = usingCachedImage ? cachedTrueColor : liveTrueColor
  const ndciHeatmapImageUrl = usingCachedImage ? cachedNdci : liveNdci

  let imageCaption = null
  let noImageMessage = null
  if (usingCachedImage) {
    imageCaption = site.actual_date
      ? `Cached scheduler reading · scene ${site.actual_date}`
      : 'Cached scheduler reading'
    if (!trueColorImageUrl && !ndciHeatmapImageUrl) {
      noImageMessage = isNoData
        ? STATUS_EXPLAINER[site.status] || 'No cached satellite image for this site yet.'
        : "The scheduler's last reading was usable, but no image was cached for it this cycle."
    }
  } else if (dt.data) {
    imageCaption = dt.data.actual_date ? `Live render · scene ${dt.data.actual_date}` : 'Live render'
    if (!trueColorImageUrl && !ndciHeatmapImageUrl) {
      noImageMessage =
        dt.data.status !== 'ok'
          ? STATUS_EXPLAINER[dt.data.status] || dt.data.reason || 'No satellite image available for today.'
          : 'No satellite image available for today.'
    }
  }

  // Only render the image block once its data source has actually
  // resolved: the cached path is synchronous (already on `site`), the
  // live path needs /detect's fetch to finish first — otherwise this
  // would flash a premature "no image" state before dt.data arrives.
  const imageSectionReady = usingCachedImage || (!!dt.data && !dt.loading && !dt.error)

  return (
    <aside className="site-panel" aria-label={`Detail panel for ${site.name}`}>
      <div className="site-panel-header">
        <div>
          <div className="site-name">{site.name}</div>
          <div className="site-coords mono">
            {site.lat.toFixed(4)}°N, {site.lng.toFixed(4)}°E
          </div>
        </div>
        <button
          ref={closeBtnRef}
          type="button"
          className="site-panel-close"
          onClick={onClose}
          aria-label="Close site panel"
        >
          ×
        </button>
      </div>

      {/* --- Prediction (risk_level / triggered_rules) — indicative --- */}
      <section>
        <div className="section-title">Predicted risk (indicative)</div>
        <span className={`risk-pill${isNoData ? ' no-data' : ''}`}>
          <span
            className="dot"
            style={riskColorVar && !isNoData ? { background: `var(${riskColorVar})` } : undefined}
          />
          {isNoData ? STATUS_LABEL[site.status] || 'No reading' : RISK_LABEL[site.risk_level]}
        </span>
        <p className="stat-detail" style={{ marginTop: 6 }}>
          {site.confidence_label ? formatConfidence(site.confidence_label) : null}
        </p>
        {site.stale && <div className="stale-flag">Stale — last scheduled refresh failed</div>}

        <div style={{ marginTop: 10 }}>
          <div className="section-title">Triggered rules</div>
          {site.triggered_rules && site.triggered_rules.length > 0 ? (
            <ul className="triggered-rules">
              {site.triggered_rules.map((level) => (
                <li key={level}>{RULE_DESCRIPTION[level] || level}</li>
              ))}
            </ul>
          ) : (
            <p className="no-rules">No rules currently triggered at this site.</p>
          )}
        </div>
      </section>

      {/* --- Anomaly strip + chart from /timeseries --- */}
      <section>
        <div className="section-title">Anomaly, last 90 days</div>
        {ts.loading && <p className="no-rules">Loading time series…</p>}
        {ts.error && (
          <div className="state-panel error">
            <h3>Couldn&apos;t reach the data service.</h3>
            <button type="button" className="retry-btn" onClick={ts.refetch}>Retry</button>
          </div>
        )}
        {ts.data && (
          <>
            <AnomalyStrip
              segments={segmentsFromTimeseries(ts.data.points, 90)}
              leftLabel="90 days ago"
              rightLabel="most recent"
              caption="Colour = how far chlorophyll is from this site's seasonal baseline. Hatched = no reading that day."
            />
            <TimeSeriesChart points={ts.data.points} />
          </>
        )}
      </section>

      {/* --- Satellite image: cached (fast, from the map's own risk-map
          fetch) when opened from a marker, live /detect render otherwise --- */}
      <section>
        <div className="section-title">Satellite image</div>
        {!usingCachedImage && dt.loading && <p className="no-rules">Checking today&apos;s satellite pass…</p>}
        {!usingCachedImage && dt.error && (
          <div className="state-panel error">
            <h3>Couldn&apos;t reach the data service.</h3>
            <button type="button" className="retry-btn" onClick={dt.refetch}>Retry</button>
          </div>
        )}
        {imageSectionReady && (
          <SatelliteImage
            trueColorUrl={trueColorImageUrl}
            ndciHeatmapUrl={ndciHeatmapImageUrl}
            noImageMessage={noImageMessage}
            caption={imageCaption}
          />
        )}
      </section>

      {/* --- Detection verdict from /detect — high confidence, separate claim --- */}
      <section>
        <div className="section-title">Detection verdict, today</div>
        {dt.loading && <p className="no-rules">Checking today&apos;s satellite pass…</p>}
        {dt.error && (
          <div className="state-panel error">
            <h3>Couldn&apos;t reach the data service.</h3>
            <button type="button" className="retry-btn" onClick={dt.refetch}>Retry</button>
          </div>
        )}
        {dt.data && dt.data.status !== 'ok' && (
          <div className="status-banner">
            <strong>{STATUS_LABEL[dt.data.status] || dt.data.status}</strong>
            <p>{STATUS_EXPLAINER[dt.data.status] || dt.data.reason || 'No detection could be run for today.'}</p>
          </div>
        )}
        {dt.data && dt.data.status === 'ok' && (
          <div className="detect-block">
            <div className="detect-verdict">
              {dt.data.detected ? 'Bloom-like signal detected' : 'No bloom-like signal detected'}
            </div>
            <dl className="detect-grid">
              <dt>Index used</dt>
              <dd className="mono">{dt.data.index_used}</dd>
              <dt>Anomaly z-score</dt>
              <dd className="mono">
                {formatZ(dt.data.anomaly_z)}
                <span className="approx-marker">approx</span>
              </dd>
              <dt>Scene date</dt>
              <dd className="mono">{dt.data.actual_date || '—'}</dd>
              <dt>Cloud fraction</dt>
              <dd className="mono">
                {dt.data.cloud_fraction != null ? `${Math.round(dt.data.cloud_fraction * 100)}%` : '—'}
              </dd>
            </dl>
          </div>
        )}
      </section>
    </aside>
  )
}
