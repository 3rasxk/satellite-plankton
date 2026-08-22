import { zToColorVar } from '../constants.js'

/**
 * Signature component (docs/FRONTEND_PLAN.md §4): a horizontal ribbon of
 * colour segments using the same ramp as the map, compressing "is this
 * unusual for this time of year?" into one glance.
 *
 * Generic over what a "segment" is — a day (site panel, from /timeseries)
 * or a monitored site (summary page region strip, from /risk-map, since
 * /summary has no historical region series to draw a day-axis from; see
 * SummaryPage.jsx for that reasoning). Each segment just needs a `z`
 * (anomaly_z or null) and a `tooltip` string; colour bucketing and the
 * no-data hatch pattern are identical either way, which is the point —
 * one visual language for "how far from baseline," never a claim beyond
 * that.
 */
export default function AnomalyStrip({ segments, leftLabel, rightLabel, caption }) {
  if (!segments || segments.length === 0) {
    return (
      <div className="anomaly-strip">
        <div className="anomaly-strip-band">
          <div className="anomaly-strip-segment no-data" style={{ flex: '1 1 100%' }} />
        </div>
        <p className="anomaly-strip-caption">No anomaly data yet for this range.</p>
      </div>
    )
  }

  return (
    <div className="anomaly-strip">
      <div className="anomaly-strip-band" role="img" aria-label={caption || 'Chlorophyll anomaly strip'}>
        {segments.map((seg, i) => {
          const colorVar = zToColorVar(seg.z)
          return (
            <div
              key={seg.key ?? i}
              className={`anomaly-strip-segment${colorVar ? '' : ' no-data'}`}
              style={colorVar ? { background: `var(${colorVar})` } : undefined}
              title={seg.tooltip}
            />
          )
        })}
      </div>
      {(leftLabel || rightLabel) && (
        <div className="anomaly-strip-axis">
          <span>{leftLabel}</span>
          <span>{rightLabel}</span>
        </div>
      )}
      {caption && <p className="anomaly-strip-caption">{caption}</p>}
    </div>
  )
}
