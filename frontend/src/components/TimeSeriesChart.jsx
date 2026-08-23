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
          <CartesianGrid strokeDasharray="2 4" stroke="rgba(60,60,67,0.08)" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
            tickLine={false}
            axisLine={{ stroke: 'rgba(60,60,67,0.12)' }}
            minTickGap={40}
          />
          <YAxis
            tick={{ fontSize: 11, fill: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
            tickLine={false}
            axisLine={false}
            width={40}
            label={{
              value: 'chlor_a (mg/m³)',
              angle: -90,
              position: 'insideLeft',
              fontSize: 10,
              fill: 'var(--text-secondary)',
            }}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--surface-raised)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
            }}
            labelStyle={{ color: 'var(--text-secondary)' }}
            itemStyle={{ color: 'var(--text)' }}
          />
          <ReferenceLine y={0} stroke="var(--border)" />
          {/* Primary trace uses --accent rather than a risk-ramp colour:
              this is a raw MODIS chlor_a line, not one of the 4 discrete
              risk tiers, so a risk token would misleadingly imply a tier
              reading. Accent blue as the single data-trace colour mirrors
              how Apple's own first-party chart-driven apps (Health,
              Stocks) use systemBlue for a primary non-categorical trace —
              it's a deliberate exception to "accent = interactive only"
              for the one chart in the app with a single, un-categorised
              series. See RegionTrendChart.jsx for the multi-line case,
              which intentionally does NOT use accent or risk colours. */}
          <Line
            type="monotone"
            dataKey="chlor_a"
            stroke="var(--accent)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
