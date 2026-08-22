import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from 'recharts'

/**
 * MODIS chlor_a time series for the clicked/summary site. `points` is the
 * raw /timeseries `points` array — chlor_a is a real MODIS reading,
 * cloud_fraction/actual_date are always null here (bulk MODIS series, not
 * a Sentinel-2 single-date pull; see backend/src/schemas.py
 * TimeseriesPoint docstring) so this chart never renders those fields.
 */
export default function TimeSeriesChart({ points }) {
  if (!points || points.length === 0) {
    return (
      <div className="chart-wrap">
        <p className="no-rules">No MODIS history returned for this coordinate.</p>
      </div>
    )
  }

  const data = points.map((p) => ({
    date: p.date,
    chlor_a: p.chlor_a,
  }))

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="rgba(122,154,181,0.15)" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: 'var(--ink-dim)', fontFamily: 'var(--font-mono)' }}
            tickLine={false}
            axisLine={{ stroke: 'rgba(122,154,181,0.2)' }}
            minTickGap={40}
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
            itemStyle={{ color: 'var(--ink)' }}
          />
          <ReferenceLine y={0} stroke="rgba(122,154,181,0.3)" />
          <Line
            type="monotone"
            dataKey="chlor_a"
            stroke="var(--clear)"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
