/**
 * Right glass detail panel (400px) for a selected station (design
 * reference): header (name, province, coordinates in mono, round close
 * button); classification pill + one-line headline; the anomaly gauge and
 * "Recommended action" only when the backend supplies them; "Basis for
 * classification"; segmented tabs Trend | Measurements | Imagery (Trend
 * first); footer with sources.
 *
 * Data source: the station from ./model.js (GET /risk-map), the MODIS-Aqua
 * series from GET /timeseries (asked once the panel is open), the cached
 * scene images from GET /risk-map/{id}/image.
 *
 * Honesty: risk class, gauge zones and basis come only from `risk_level`,
 * `triggered_rules`, `confidence_label`. With the TEST baseline there is no
 * class: the pill reads "Not evaluated" in neutral grey, the gauge zones
 * and the action card are not drawn, and the TEST robust z is shown as a
 * plain number with its caveat. Missing values read "—" with the reason.
 * No sample data, and no series the API does not return.
 */
import { Suspense, lazy, useCallback, useMemo, useState } from 'react'
import { CloseIcon, Seg } from './ui.jsx'
import { LV, fmtIndex, fmtZ } from './model.js'
import { getTimeseries } from '../api/client.js'
import { useApi } from '../hooks/useApi.js'
import CellImagery from './CellImagery.jsx'
import SentinelView from './SentinelView.jsx'
import { useSatelliteImage } from '../hooks/useSatelliteImage.js'
import { TIMESERIES_TIMEOUT_MS, modisChartData } from '../lib/sitesModel.js'

const TrendChart = lazy(() => import('./TrendChart.jsx'))
const YEAR_MS = 365 * 24 * 3600 * 1000

function useSeries(lat, lng) {
  const fetchSeries = useCallback(function fetchSeries() {
    return getTimeseries(lat, lng, { timeout: TIMESERIES_TIMEOUT_MS })
  }, [lat, lng])
  const r = useApi(fetchSeries, [lat, lng], { enabled: lat !== null && lng !== null })
  const ok = !r.loading && r.data && r.data.lat === lat && r.data.lng === lng
  return { data: ok ? r.data : null, loading: r.loading, error: r.error, refetch: r.refetch }
}

function ruleText(r) {
  if (typeof r === 'string') return r
  return r.description ?? r.rule ?? r.name ?? JSON.stringify(r)
}

function Classification({ s }) {
  const lv = LV[s.cls]
  const pillBg = lv.hollow ? '#E5E5EA' : lv.color
  let headline
  if (s.rated) headline = `${lv.label}: see the basis below.`
  else if (s.testClass) headline = `${lv.label}: robust z ${fmtZ(s.z)} against this location’s own seasonal history. A provisional indication, not a bloom detection.`
  else if (s.cls === 'unrated') headline = `Index reading from the Sentinel-2 scene of ${s.date ?? '—'}. Risk is not evaluated.`
  else if (s.cls === 'unchecked') headline = 'The first scheduled check has not finished. This is loading, not a finding.'
  else headline = s.reason ? `No usable observation: ${s.reason}` : 'No cloud-free observation is available for this station.'
  return (
    <section className="gl-card">
      <div className="gl-pill-row">
        <span className="gl-pill" style={{ color: lv.on, background: pillBg }}><i />{lv.label}</span>
        {s.stale && <span className="gl-chip">Out of date</span>}
        <span>{s.rated ? 'Rule-based · indicative' : s.testClass ? 'Provisional · uncalibrated' : s.cls === 'unrated' ? 'No risk class' : 'Not a finding'}</span>
      </div>
      <p className="gl-headline">{headline}</p>
    </section>
  )
}

function Anomaly({ s }) {
  if (s.z === null) return null
  const pct = Math.min(100, Math.max(0, ((s.z + 2) / 5) * 100))
  return (
    <section className="gl-sec">
      <div className="gl-sec-head">
        <b>{s.rated ? 'Anomaly vs. seasonal baseline' : 'Anomaly vs own history'}</b>
        <span className="gl-mono" style={{ fontSize: 13, whiteSpace: 'nowrap', flex: 'none', marginLeft: 8 }}>z {fmtZ(s.z)} <span style={{ color: '#8E8E93', fontFamily: 'inherit' }}>approx.</span></span>
      </div>
      {s.rated || s.testClass ? (
        <>
          <div className="gl-gauge" aria-hidden="true">
            <div className="gl-gauge-track"><div style={{ width: '70%', background: '#D1D1D6' }} /><div style={{ width: '10%', background: '#FFCC00' }} /><div style={{ width: '20%', background: '#FF3B30' }} /></div>
            <div className="gl-gauge-mark" style={{ left: `${pct}%` }} />
          </div>
          <div className="gl-gauge-zones"><span>Within baseline</span><span>Anomalous</span><span style={{ textAlign: 'right' }}>Strongly anomalous</span></div>
        </>
      ) : (
        <p className="gl-note">A statistic against this location’s own seasonal history. Uncalibrated, boundaries provisional; not a risk class.</p>
      )}
    </section>
  )
}

function Basis({ s }) {
  const items = []
  if (s.rated) {
    s.triggeredRules.forEach((r) => items.push(ruleText(r)))
    if (items.length === 0) items.push('The API listed no triggered rules for this class.')
  } else if (s.testClass) {
    items.push('Robust z of NDCI against this location’s own seasonal history.')
    items.push('Watch at z ≥ 2.0 and Warning at z ≥ 3.0: provisional engineering thresholds, not validated bloom thresholds.')
    items.push('Risk is not evaluated: no validated baseline or calibrated rule exists.')
  } else if (s.cls === 'unrated') {
    items.push('Risk is not evaluated: no validated baseline or calibrated rule exists.')
    if (s.z !== null) items.push('z is a robust z of NDCI against this location’s own seasonal history.')
  } else if (s.cls === 'unchecked') {
    items.push('Appears after a restart; the pin is hollow, same as “no reading”.')
  } else {
    items.push('No cloud-free acquisition in the search window. Absence of data is not evidence of absence of a bloom.')
  }
  if (s.stale) items.push('The last refresh failed; this is the most recent good reading.')
  return (
    <section className="gl-sec">
      <b>Basis for classification</b>
      <ul className="gl-bullets">{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
    </section>
  )
}

function Trend({ series, s }) {
  const points = useMemo(() => {
    const all = modisChartData(series.data).filter((p) => p.chlor_a !== null)
    if (all.length === 0) return []
    const end = all[all.length - 1].t
    return all.filter((p) => p.t >= end - YEAR_MS)
  }, [series.data])
  const last = points.length ? points[points.length - 1] : null
  return (
    <section className="gl-card gl-card--14">
      <div className="gl-title13">Chlorophyll-a, last 12 months</div>
      <div className="gl-sub12">mg/m³ · MODIS-Aqua, ~4.6 km grid (a separate sensor from the Sentinel-2 readings)</div>
      {series.loading && <p className="gl-note">Fetching the MODIS series… the first request can take a while.</p>}
      {series.error && (
        <p className="gl-note">Couldn’t reach the data service. <button type="button" className="gl-link" onClick={series.refetch}>Retry</button></p>
      )}
      {!series.loading && !series.error && points.length === 0 && <p className="gl-note">—  No MODIS chlorophyll-a points for this location.</p>}
      {points.length > 0 && (
        <>
          <Suspense fallback={<div className="gl-skel" style={{ height: 140 }} />}>
            <TrendChart points={points} />
          </Suspense>
          <div className="gl-legend-inline"><span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span style={{ width: 14, height: 3, borderRadius: 2, background: '#0071E3', display: 'block' }} />MODIS chlor_a</span></div>
          {last && <p className="gl-note" style={{ marginTop: 6 }}>Latest MODIS point {new Date(last.t).toISOString().slice(0, 10)}: <span className="gl-mono">{last.chlor_a.toFixed(2)}</span> mg/m³{last.anomaly_z !== null ? <> · z <span className="gl-mono">{fmtZ(last.anomaly_z)}</span> vs MODIS day-of-year climatology</> : null}.</p>}
        </>
      )}
      {s.cls === 'none' && <p className="gl-note">No daily classification is stored for this station.</p>}
    </section>
  )
}

function Measurements({ s, series }) {
  const pts = modisChartData(series.data).filter((p) => p.chlor_a !== null)
  const lastP = pts.length ? pts[pts.length - 1] : null
  const rows = [
    { name: 'Chlorophyll-a', plain: lastP ? `MODIS-Aqua, ${new Date(lastP.t).toISOString().slice(0, 10)}` : series.loading ? 'Loading the MODIS series…' : 'No MODIS point available', value: lastP ? lastP.chlor_a.toFixed(2) : '—', unit: 'mg/m³' },
    { name: 'NDCI (approx.)', plain: 'Normalised Difference Chlorophyll Index, Sentinel-2', value: fmtIndex(s.ndci), unit: '' },
    { name: '2BDA', plain: 'Two-band ratio algorithm', value: fmtIndex(s.bda2), unit: '' },
    { name: '3BDA', plain: 'Three-band ratio algorithm', value: fmtIndex(s.bda3), unit: '' },
    { name: 'Sea surface temperature', plain: 'Not yet exposed by the API', value: '—', unit: '°C' },
    { name: 'Rainfall, 7-day cumulative', plain: 'Not yet exposed by the API', value: '—', unit: 'mm' },
  ]
  return (
    <section>
      <div className="gl-inset">
        {rows.map((r) => (
          <div className="gl-meas" key={r.name}>
            <div><b>{r.name}</b><small>{r.plain}</small></div>
            <div className="gl-mono gl-val">{r.value}<small>{r.unit}</small></div>
          </div>
        ))}
      </div>
      <p className="gl-foot12">Values marked approx. are satellite estimates: reliable for presence and absence, approximate for concentration. A dash means no source is available yet.</p>
    </section>
  )
}

function Imagery({ s, raster }) {
  const [pm, setPm] = useState('rgb')
  const [fine, setFine] = useState(null)
  const lat = s.cell?.lat ?? s.pinLat ?? s.lat
  const lng = s.cell?.lng ?? s.pinLng ?? s.lng
  const date = s.date
  // The exact Sentinel-2 scene (10 m) around the pin, rendered live: its true
  // colour, and its NDCI as a filter over it (same scene, same extent).
  const base = lat != null && lng != null && date ? `/satellite-image?lat=${lat}&lng=${lng}&date=${date}&image_type=` : null
  const tc = useSatelliteImage(base ? `${base}true_color` : null)
  const nd = useSatelliteImage(base && pm === 'ndci' ? `${base}ndci_heatmap` : null)
  const sentinelOk = base && !tc.error && !(pm === 'ndci' && nd.error)
  const waiting = base && (tc.loading || (pm === 'ndci' && nd.loading))
  let body
  if (sentinelOk && waiting) body = 'Rendering the Sentinel-2 image… this takes a few seconds.'
  else if (sentinelOk) body = <SentinelView trueSrc={tc.objectUrl} ndciSrc={pm === 'ndci' ? nd.objectUrl : null} label={`${pm === 'rgb' ? 'True-colour' : 'NDCI over true-colour'} Sentinel-2 image around the pin`} />
  else body = <CellImagery raster={raster} lat={lat} lng={lng} mode={pm} onFine={setFine} />
  const fallbackNote = tc.error || (pm === 'ndci' && nd.error) || !base
  return (
    <section className="gl-sec" style={{ gap: 10 }}>
      <Seg className="gl-seg--tabs" options={[['rgb', 'True colour'], ['ndci', 'NDCI']]} value={pm} onChange={setPm} label="Image type" />
      <div className="gl-photo" style={{ padding: 0 }}>{body}</div>
      <div className="gl-sub12" style={{ color: '#8E8E93' }}>
        {sentinelOk
          ? `Sentinel-2 L2A scene of ${date ?? '—'} (10 m), rendered live around the pin${pm === 'ndci' ? '; its NDCI is laid over the true-colour image as a filter. Higher NDCI means higher chlorophyll (approx.), not a risk level' : ''}.`
          : `${fallbackNote ? (tc.error || nd.error || 'No scene date for this location, so no Sentinel-2 image can be rendered.') + ' Showing satellite imagery' : 'Satellite imagery'} (Esri World Imagery)${pm === 'ndci' ? ` with the map’s NDCI (${fine ? 'per pixel, about 40 m' : '200 m cells'}) over it` : ''}, about 2 km across.`}
      </div>
    </section>
  )
}

export default function DetailPanel({ station: s, onClose, raster }) {
  const [tab, setTab] = useState('trend')
  const series = useSeries(s.lat, s.lng)
  const coords = s.lat !== null && s.lng !== null ? `${s.lat.toFixed(2)}°N, ${s.lng.toFixed(2)}°E` : '—'
  return (
    <aside className="gl-right gl-glass" aria-label="Station details">
      <div className="gl-grab" aria-hidden="true" />
      <div className="gl-right-head">
        <div style={{ minWidth: 0 }}>
          <h3>{s.short}</h3>
          <div className="gl-right-sub">{s.province}</div>
          <div className="gl-mono gl-right-coords">{coords}</div>
        </div>
        <button type="button" className="gl-round gl-round--sm" aria-label="Close" onClick={onClose}><CloseIcon /></button>
      </div>
      <div className="gl-right-body">
        <Classification s={s} />
        <Anomaly s={s} />
        <Basis s={s} />
        <Seg className="gl-seg--tabs" options={[['trend', 'Trend'], ['nums', 'Measurements'], ['photo', 'Imagery']]} value={tab} onChange={setTab} label="Station detail" />
        {tab === 'trend' && <Trend series={series} s={s} />}
        {tab === 'nums' && <Measurements s={s} series={series} />}
        {tab === 'photo' && <Imagery s={s} raster={raster} />}
        <div className="gl-sources">
          Sources: Sentinel-2, MODIS. Rule-based and indicative; not a validated forecast.
        </div>
      </div>
    </aside>
  )
}
