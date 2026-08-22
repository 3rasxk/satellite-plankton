import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from 'recharts'
import { mergeSiteSeries } from '../utils/series.js'

// One dash/opacity identity per site line. Deliberately NOT drawn from the
// ramp colours (--clear/--elevated/--bloom/--severe mean chlorophyll
// concentration only, per CLAUDE.md/frontend-dashboard.md non-negotiable
// rules) — every line shares the neutral --ink-dim stroke and is told
// apart by dash pattern + opacity instead, so line identity never reads
// as a risk signal.
const LINE_STYLES = [
  { dash: undefined, opacity: 1 },
  { dash: '5 3', opacity: 0.9 },
  { dash: '2 3', opacity: 0.85 },
  { dash: '8 3', opacity: 0.75 },
  { dash: '1 4', opacity: 0.65 },
  { dash: '6 2 1 2', opacity: 0.55 },
]

export default function RegionTrendChart({ sitesWithPoints }) {
  const usable = sitesWithPoints.filter((s) => s.points.length > 0)
  if (usable.length === 0) {
    return (
      <div className="chart-wrap">
        <p className="no-rules">No MODIS history returned for any monitored site.</p>
      </div>
    )
  }

  const data = mergeSiteSeries(usable)

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="rgba(122,154,181,0.15)" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: 'var(--ink-dim)', fontFamily: 'var(--font-mono)' }}
            tickLine={false}
            axisLine={{ stroke: 'rgba(122,154,181,0.2)' }}
            minTickGap={50}
          />
          <YAxis
            tick={{ fontSize: 11, fill: 'var(--ink-dim)', fontFamily: 'var(--font-mono)' }}
            tickLine={false}
            axisLine={false}
            width={40}
            label={{
              value: 'chlor_a (mg/m³)',
              angle: -90,
              position: 'insideLeft',
              fontSize: 10,
              fill: 'var(--ink-dim)',
            }}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--deep)',
              border: '1px solid rgba(122,154,181,0.3)',
              borderRadius: 2,
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
            }}
            labelStyle={{ color: 'var(--ink-dim)' }}
          />
          <Legend
            wrapperStyle={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-dim)' }}
          />
          {usable.map(({ site }, i) => {
            const style = LINE_STYLES[i % LINE_STYLES.length]
            return (
              <Line
                key={site.site_id}
                type="monotone"
                dataKey={site.site_id}
                name={site.name}
                stroke="var(--ink-dim)"
                strokeOpacity={style.opacity}
                strokeDasharray={style.dash}
                strokeWidth={1.5}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            )
          })}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
