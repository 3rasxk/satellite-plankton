/**
 * Chlorophyll-a trend (Recharts): #0071E3 line with a round dot at the latest
 * point. Loaded lazily by DetailPanel.
 *
 * Data source: `points` = GET /timeseries points (MODIS-Aqua `chlor_a`,
 * mg/m³), last 12 months before the newest point. Nothing is interpolated or
 * filled; a null value is a gap. The API returns no climatology series, so
 * there is no dashed climatology line.
 */
import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from 'recharts'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const tick = { fontSize: 10, fill: '#8E8E93' }

export default function TrendChart({ points }) {
  const last = points.length ? points[points.length - 1] : null
  const dot = (p) => (p.payload === last
    ? <circle key="last" cx={p.cx} cy={p.cy} r={4.5} fill="#0071E3" stroke="#fff" strokeWidth={2} />
    : <g key={p.index} />)
  return (
    <div style={{ width: '100%', height: 140 }} role="img" aria-label="Chlorophyll-a trend, MODIS-Aqua, last 12 months">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="#E5E5EA" vertical={false} />
          <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} tick={tick} tickLine={false} axisLine={false} minTickGap={28} tickFormatter={(ms) => MONTHS[new Date(ms).getUTCMonth()]} />
          <YAxis tick={tick} tickLine={false} axisLine={false} width={40} domain={[0, 'auto']} tickFormatter={(v) => (v >= 10 ? Math.round(v) : v.toFixed(1))} />
          <Line type="monotone" dataKey="chlor_a" stroke="#0071E3" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" dot={dot} activeDot={false} isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
