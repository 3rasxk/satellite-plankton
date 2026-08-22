import { RISK_LABEL, RISK_MEANING, RISK_COLOR_VAR } from '../constants.js'

const LEVELS = ['normal', 'elevated', 'watch', 'warning']

/**
 * Fixed legend for the risk map. Shows what each colour means, not just
 * the swatch (docs/FRONTEND_PLAN.md §5: "showing the three [now four]
 * levels *with what they mean*"). The no-data hatch pattern is listed
 * separately and explicitly labelled as "not a risk reading" so it can
 * never be misread as the lowest risk tier.
 */
export default function RiskLegend() {
  return (
    <div className="risk-legend">
      <h3>Risk level</h3>
      {LEVELS.map((level) => (
        <div className="legend-row" key={level}>
          <span
            className="legend-swatch"
            style={{ background: `var(${RISK_COLOR_VAR[level]})` }}
          />
          <span>
            <span className="legend-label">{RISK_LABEL[level]}</span>
            <span className="legend-meaning">{RISK_MEANING[level]}</span>
          </span>
        </div>
      ))}
      <div className="legend-row">
        <span className="legend-swatch no-data" />
        <span>
          <span className="legend-label">No reading</span>
          <span className="legend-meaning">
            Cloud cover, missing baseline, or not yet checked — not a risk level.
          </span>
        </span>
      </div>
    </div>
  )
}
