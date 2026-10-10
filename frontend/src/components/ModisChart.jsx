/**
 * ModisChart: the two scatter panels of the MODIS-Aqua series -- `chlor_a`
 * (mg m⁻³) above, `anomaly_z` (dimensionless) below -- one axis and one
 * quantity per panel (dashboard spec §4.3). Loaded lazily by ModisSeries,
 * so the charting library is fetched only when a site page shows a series.
 *
 * Data source: `modis.chart` from src/lib/sitesModel.js `modisChartData`
 * (GET /timeseries points: epoch-ms time for the axis, the API's chlor_a
 * and anomaly_z). One dot per API point; a null value is not drawn (never
 * as 0); nothing is averaged, interpolated or filled. Dots, no line: the
 * observations are irregular. Marks are ink, never a risk or accent colour.
 */
import {
  CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts'
import { formatValue } from '../lib/format.js'

const PANEL_HEIGHT = 180
const AXIS_TICK = { fontSize: 12, fill: 'var(--ink-3)', fontFamily: 'var(--font-mono)' }
const yearOf = (ms) => (Number.isFinite(ms) ? new Date(ms).toISOString().slice(0, 4) : '')

function ChartTip({ active, payload, field, spec }) {
  if (!active || !Array.isArray(payload) || payload.length === 0) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <div className="pw-modis-tip">
      <span className="pw-mono">{point.date}</span>
      <span className="pw-mono">{formatValue(point[field], spec).text}</span>
    </div>
  )
}

function Panel({ data, field, label, spec, zeroLine = false }) {
  const points = data.filter((p) => p[field] !== null)
  return (
    <div className="pw-modis-panel">
      <p className="pw-modis-axis-label">{label}</p>
      <div style={{ width: '100%', height: PANEL_HEIGHT }}>
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke="var(--line-soft)" vertical={false} />
            <XAxis
              type="number"
              dataKey="t"
              domain={['dataMin', 'dataMax']}
              scale="time"
              tickFormatter={yearOf}
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={{ stroke: 'var(--line)' }}
              minTickGap={24}
            />
            <YAxis
              type="number"
              dataKey={field}
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={{ stroke: 'var(--line)' }}
              width={48}
              tickFormatter={(v) => formatValue(v, { kind: 'z', decimals: Math.abs(v) >= 10 ? 0 : 1 }).text}
            />
            <ZAxis range={[14, 14]} />
            {zeroLine && <ReferenceLine y={0} stroke="var(--line-strong)" strokeDasharray="3 3" />}
            <Tooltip cursor={false} content={<ChartTip field={field} spec={spec} />} isAnimationActive={false} />
            <Scatter data={points} fill="var(--ink-2)" fillOpacity={0.7} isAnimationActive={false} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default function ModisChart({ data, chlLabel, zLabel }) {
  const points = Array.isArray(data) ? data : []
  return (
    <>
      <Panel data={points} field="chlor_a" label={chlLabel} spec={{ kind: 'mg-m3' }} />
      <Panel data={points} field="anomaly_z" label={zLabel} spec={{ kind: 'z' }} zeroLine />
    </>
  )
}
