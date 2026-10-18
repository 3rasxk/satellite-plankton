/**
 * /summary: regional summary (design reference) -- one card per class with
 * a count, the strongest TEST anomaly with a "View on map" button, a
 * Limitations card, and the all-stations strip and table (a row opens the
 * map with that station selected).
 *
 * Data source: GET /risk-map (stations), GET /raster-scan (newest scene,
 * via the shell), GET /timeseries per row (MODIS chlor_a, last 90 days of
 * the series, for the sparkline). No sample data. With the TEST baseline
 * there is no risk class: the cards count "Not evaluated" / "No data", the
 * z column is the TEST robust z against the station's own history, and the
 * "most recent signal" card is the highest TEST z -- not a detection.
 */
import { useCallback, useMemo } from 'react'
import { Link, useNavigate, useOutletContext } from 'react-router-dom'
import { Dot } from './ui.jsx'
import { LV, countsOf, fmtZ, swatchStyle } from './model.js'
import useStations from './useStations.js'
import { NoSignal, Skeleton, Unreachable } from './StateViews.jsx'
import { getTimeseries } from '../api/client.js'
import { useApi } from '../hooks/useApi.js'
import { TIMESERIES_TIMEOUT_MS, modisChartData } from '../lib/sitesModel.js'

const HATCH = 'repeating-linear-gradient(135deg,#D1D1D6 0 3px,#F2F2F7 3px 6px)'
const DAY = 24 * 3600 * 1000

function ago(iso) {
  const t = Date.parse(iso ?? '')
  if (!Number.isFinite(t)) return '—'
  const h = Math.max(0, Math.round((Date.now() - t) / 3600000))
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} d ago`
}

function Spark({ lat, lng }) {
  const fetchSeries = useCallback(function fetchSeries() {
    return getTimeseries(lat, lng, { timeout: TIMESERIES_TIMEOUT_MS })
  }, [lat, lng])
  const r = useApi(fetchSeries, [lat, lng], { enabled: lat !== null && lng !== null })
  const pts = useMemo(() => {
    const all = modisChartData(r.data).filter((p) => p.chlor_a !== null)
    if (all.length < 2) return []
    const end = all[all.length - 1].t
    return all.filter((p) => p.t >= end - 90 * DAY)
  }, [r.data])
  if (r.loading) return <span className="gl-skel" style={{ display: 'block', width: 120, height: 10 }} aria-label="Loading" />
  if (pts.length < 2) return <span className="gl-last" title="No MODIS chlor_a points in the last 90 days of the series">—</span>
  const ys = pts.map((p) => p.chlor_a)
  const lo = Math.min(...ys)
  const hi = Math.max(...ys)
  const t0 = pts[0].t
  const span = pts[pts.length - 1].t - t0 || 1
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${(2 + ((p.t - t0) / span) * 116).toFixed(1)} ${(26 - ((p.chlor_a - lo) / (hi - lo || 1)) * 24).toFixed(1)}`).join(' ')
  return (
    <svg width="120" height="28" viewBox="0 0 120 28" role="img" aria-label="MODIS chlorophyll-a, last 90 days of the series">
      <path d={d} fill="none" stroke="#0071E3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export default function SummaryPage() {
  const { risk, scan } = useOutletContext()
  const navigate = useNavigate()
  const stations = useStations()
  const open = (id) => navigate(`/map?site=${encodeURIComponent(id)}`)
  const newest = scan.data?.newest_scene_date
  const oldest = scan.data?.oldest_scene_date
  const counts = stations ? countsOf(stations) : []
  const top = stations ? [...stations].filter((s) => s.z !== null).sort((a, b) => b.z - a.z)[0] : null
  const classified = stations?.some((s) => s.rated || s.testClass)
  const rated = stations?.some((s) => s.rated)
  const attention = stations ? stations.filter((s) => s.cls === 'warning' || s.cls === 'watch').length : 0

  return (
    <div className="gl-scroll">
      <div className="gl-page">
        <div>
          <h1>Regional summary</h1>
          <p className="gl-page-sub">
            {stations
              ? `${classified ? `${attention} ${attention === 1 ? 'station requires' : 'stations require'} attention` : `${stations.filter((s) => s.hasReading).length} of ${stations.length} stations have an index reading; risk is not evaluated`}`
              : 'Loading…'}
            {newest ? ` · Newest scene ${newest}${oldest && oldest !== newest ? `, oldest ${oldest}` : ''}.` : ''}
          </p>
        </div>

        {!stations && !risk.error && <div className="gl-surface"><Skeleton /></div>}
        {risk.error && !stations && <div className="gl-surface"><Unreachable onRetry={risk.refetch} /></div>}

        {stations && (
          <>
            <section className="gl-stats">
              {counts.map((c) => (
                <div className="gl-surface gl-stat" key={c.key}>
                  <span className="gl-stat-label"><Dot cls={c.key} />{c.label}</span>
                  <span className="gl-stat-n gl-mono">{c.n}</span>
                  <span className="gl-stat-meaning">{c.meaning}</span>
                </div>
              ))}
            </section>

            <section className="gl-two">
              <div className="gl-surface">
                <span className="gl-eyebrow">{rated ? 'Most recent detected signal' : 'Strongest signal'}</span>
                {top ? (
                  <>
                    <span className="gl-big">{top.short}, {top.province}</span>
                    <span style={{ fontSize: 14, color: '#3A3A3C' }}>
                      Checked {ago(top.fetchedAt)} · scene {top.date ?? '—'} · <span className="gl-mono">z {fmtZ(top.z)}</span> approx.
                    </span>
                    {!rated && <span className="gl-note">Compared with its own seasonal history. Thresholds are provisional and uncalibrated: an indication, not a bloom detection.</span>}
                    <div><button type="button" className="gl-btn" onClick={() => open(top.id)}>View on map</button></div>
                  </>
                ) : <NoSignal />}
              </div>
              <div className="gl-surface">
                <span className="gl-eyebrow">Limitations</span>
                <span style={{ fontSize: 14 }}><strong>Detection</strong> of a current anomaly is standard remote sensing at satellite pixel resolution. <strong>Prediction</strong> of rising risk is rule-based and indicative, not a validated forecast{rated ? '' : ' — and currently not evaluated: no validated baseline or calibrated rule exists'}.</span>
                <span style={{ fontSize: 13, color: '#6E6E73' }}>Small or dispersed blooms may be missed. Thresholds are not locally calibrated against recorded bloom events.</span>
                <span style={{ fontSize: 13 }}><Link to="/data">Data &amp; limits</Link> · <Link to="/methods">Methods</Link></span>
              </div>
            </section>

            <section className="gl-surface" style={{ gap: 14 }}>
              <div className="gl-sec-head"><span style={{ fontSize: 17, fontWeight: 600 }}>All stations</span><span style={{ fontSize: 13, color: '#8E8E93' }}>Select a row to view on the map</span></div>
              <div className="gl-strip" role="img" aria-label="Class of each station, in severity order">
                {stations.map((s) => <div key={s.id} title={`${s.short}: ${LV[s.cls].label}`} style={LV[s.cls].hollow ? { background: HATCH } : swatchStyle(s.cls)} />)}
              </div>
              <div className="gl-table-wrap">
                <table className="gl-table">
                  <thead>
                    <tr><th>Station</th><th>Class</th><th>z (approx.)</th><th>Chlorophyll-a, 90 d</th><th>Last observation</th></tr>
                  </thead>
                  <tbody>
                    {stations.map((s) => (
                      <tr key={s.id} onClick={() => open(s.id)}>
                        <td><button type="button" className="gl-link" style={{ fontSize: 14, fontWeight: 600, color: 'inherit' }} onClick={(e) => { e.stopPropagation(); open(s.id) }}>{s.short}</button><small>{s.province}</small></td>
                        <td><span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}><Dot cls={s.cls} />{LV[s.cls].label}</span></td>
                        <td className="gl-mono">{fmtZ(s.z)}</td>
                        <td><Spark lat={s.lat} lng={s.lng} /></td>
                        <td className="gl-last">{s.date ? `scene ${s.date}` : s.reason ?? 'No usable pass'}{s.stale ? ' · out of date' : ''}<small>{s.fetchedAt ? `checked ${ago(s.fetchedAt)}` : ''}</small></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  )
}
