import { useCallback, useMemo } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getSummary, getRiskMap, getTimeseries } from '../api/client.js'
import StatCard from '../components/StatCard.jsx'
import AnomalyStrip from '../components/AnomalyStrip.jsx'
import RegionTrendChart from '../components/RegionTrendChart.jsx'
import { formatRelativeTime, formatZ } from '../constants.js'

/**
 * Summary page (docs/FRONTEND_PLAN.md §5). /summary gives current
 * region-wide counts but no historical region series, so the region
 * AnomalyStrip and trend chart are built from /risk-map's per-site
 * snapshot + each site's own /timeseries history respectively — both are
 * real per-site data, never a fabricated aggregate number (see
 * RegionTrendChart.jsx / AnomalyStrip.jsx comments for the reasoning).
 */
export default function SummaryPage() {
  const summaryApi = useApi(getSummary, [])
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
      })),
    [riskMapApi.data],
  )

  const siteKey = sites.map((s) => s.site_id).join(',')

  const fetchTrend = useCallback(async () => {
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

  const trendApi = useApi(fetchTrend, [siteKey], { enabled: sites.length > 0 })

  const regionSegments = sites.map((s) => ({
    key: s.site_id,
    z: s.anomaly_z,
    tooltip: `${s.name}: ${s.anomaly_z == null ? 'no reading' : `z=${formatZ(s.anomaly_z)}`}`,
  }))

  const s = summaryApi.data

  return (
    <div className="page">
      <div className="page-header">
        <h1>Region summary</h1>
        <span className="updated-line">
          {s?.newest_fetched_at
            ? `Freshest reading ${formatRelativeTime(s.newest_fetched_at)} · oldest ${formatRelativeTime(s.oldest_fetched_at)}`
            : 'Sentinel-2 + MODIS · monitored grid'}
        </span>
      </div>

      {summaryApi.loading && (
        <div className="state-panel">
          <h3>Loading region summary…</h3>
        </div>
      )}

      {summaryApi.error && (
        <div className="state-panel error">
          <h3>Couldn&apos;t reach the data service. Retry.</h3>
          <button type="button" className="retry-btn" onClick={summaryApi.refetch}>Retry</button>
        </div>
      )}

      {s && (
        <>
          <section className="summary-section">
            <div className="stat-row">
              <StatCard label="Monitored sites" value={s.total_sites} />
              <StatCard label="Normal" value={s.risk_level_counts.normal} riskLevel="normal" />
              <StatCard label="Elevated" value={s.risk_level_counts.elevated} riskLevel="elevated" />
              <StatCard label="Watch" value={s.risk_level_counts.watch} riskLevel="watch" />
              <StatCard label="Warning" value={s.risk_level_counts.warning} riskLevel="warning" />
              <StatCard
                label="Not checked yet"
                value={s.risk_level_counts.not_checked_yet}
                detail="Scheduler has not reached these sites yet — a loading state, not a finding"
              />
              <StatCard
                label="No usable data"
                value={s.risk_level_counts.no_usable_data}
                detail="Read, but returned nothing usable: cloud cover, missing baseline, or a failed fetch"
              />
              <StatCard
                label="Stale sites"
                value={s.stale_site_count}
                detail="Last scheduled refresh failed for these"
              />
            </div>
          </section>

          <section className="summary-section">
            <div className="section-title">Most recent detected signal</div>
            {s.most_recent_detected_signal ? (
              <div className="detect-block" style={{ maxWidth: 420 }}>
                <div className="detect-verdict">{s.most_recent_detected_signal.name}</div>
                <dl className="detect-grid">
                  <dt>Scene date</dt>
                  <dd className="mono">{s.most_recent_detected_signal.actual_date || '—'}</dd>
                  <dt>Anomaly z-score</dt>
                  <dd className="mono">
                    {formatZ(s.most_recent_detected_signal.anomaly_z)}
                    <span className="approx-marker">approx</span>
                  </dd>
                  <dt>Checked</dt>
                  <dd className="mono">{formatRelativeTime(s.most_recent_detected_signal.fetched_at)}</dd>
                </dl>
              </div>
            ) : (
              <p className="no-rules">No recent signal — no monitored site currently has a detected bloom-like reading.</p>
            )}
          </section>

          <section className="summary-section">
            <div className="section-title">Prediction confidence</div>
            <p className="no-rules">{s.prediction_confidence_label}</p>
          </section>

          <section className="summary-section">
            <div className="section-title">Chlorophyll anomaly across monitored sites, right now</div>
            <AnomalyStrip
              segments={regionSegments}
              leftLabel={sites[0]?.name}
              rightLabel={sites[sites.length - 1]?.name}
              caption="Each band is one monitored site's current anomaly reading, not a time axis — hatched means no current reading for that site."
            />
          </section>

          <section className="summary-section">
            <div className="section-title">Site trends, last 90 days (chlorophyll, mg/m³)</div>
            {trendApi.loading && <p className="no-rules">Loading per-site history…</p>}
            {trendApi.error && (
              <div className="state-panel error">
                <h3>Couldn&apos;t reach the data service. Retry.</h3>
                <button type="button" className="retry-btn" onClick={trendApi.refetch}>Retry</button>
              </div>
            )}
            {trendApi.data && <RegionTrendChart sitesWithPoints={trendApi.data} />}
          </section>
        </>
      )}
    </div>
  )
}
