/**
 * NDCI colour bar (design reference), bottom-left glass card: title
 * "NDCI · approx.", the ramp, six ticks, "Lower chlorophyll" /
 * "Higher chlorophyll". Shown only on the NDCI basemap; stacks above the
 * basemap switch when a station is selected.
 *
 * Data source: `legend` of GET /raster-scan (`value.swatches`, `value.domain`):
 * the colours and the true range come from the API (e.g. -0.050..0.150), not
 * from this file. Only if the API sends no swatches does the design's own
 * ramp (blue, cyan, green, yellow, orange, red) stand in.
 */
import { formatValue } from '../lib/format.js'

const FALLBACK = ['#2E5FA6', '#3FA7C8', '#6CC36A', '#F2D544', '#F08A3C', '#D93A2B']

export default function NdciCard({ legend, detail }) {
  const v = legend?.value ?? {}
  const sw = (Array.isArray(v.swatches) ? v.swatches : []).map((s) => s?.hex).filter((h) => typeof h === 'string')
  const colours = sw.length >= 2 ? sw : FALLBACK
  const stops = colours.map((c, i) => `${c} ${(i / (colours.length - 1)) * 100}%`).join(',')
  const d = Array.isArray(v.domain) && v.domain.length === 2 && v.domain.every(Number.isFinite) ? v.domain : null
  const ticks = d ? Array.from({ length: 6 }, (_, i) => formatValue(d[0] + ((d[1] - d[0]) * i) / 5, { kind: 'index', decimals: 2 }).text) : []
  return (
    <div className="gl-ndci gl-glass" role="note" aria-label="NDCI colour scale">
      <div className="gl-ndci-head">
        <b>NDCI <span>· approx.</span></b>
        <small>Normalised Difference Chlorophyll Index</small>
      </div>
      <div className="gl-ndci-bar" style={{ background: `linear-gradient(90deg,${stops})` }} />
      {d && <div className="gl-ndci-ticks gl-mono">{ticks.map((t, i) => <span key={i}>{t}</span>)}</div>}
      <div className="gl-ndci-ends"><span>Lower chlorophyll</span><span>Higher chlorophyll</span></div>
      <p className="gl-ndci-note">An optical index, not a concentration or a risk level. Uncoloured sea = no NDCI (cloud, gap, or not scanned), not a low value. Outside the map extent the flat teal is a placeholder, not a measurement.{' '}
        {detail === 'ready' ? 'Detail: NDCI per pixel (about 40 m) from the same Sentinel-2 scenes.' : detail === 'loading' ? 'Rendering the per-pixel (about 40 m) NDCI… showing the 200 m cells meanwhile.' : detail === 'unavailable' ? 'The per-pixel NDCI is unavailable; showing 200 m cells.' : ''}</p>
    </div>
  )
}
