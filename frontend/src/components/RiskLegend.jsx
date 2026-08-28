import { RISK_LABEL_TH, RISK_MEANING_TH, RISK_COLOR_VAR } from '../constants.js'

const LEVELS = ['elevated', 'watch', 'warning']

/**
 * Fixed legend for the risk map. Shows what each colour means in Thai.
 * Locked in place at the bottom-left corner of the map.
 */
export default function RiskLegend() {
  return (
    <div className="risk-legend glass risk-horizontal-legend">
      <h3>ระดับความเสี่ยง</h3>
      <div className="legend-items-horizontal">
        {LEVELS.map((level) => (
          <div className="legend-col" key={level}>
            <div className="legend-col-header">
              <span className="legend-swatch" style={{ background: `var(${RISK_COLOR_VAR[level]})` }} />
              <span className="legend-label">{RISK_LABEL_TH[level]}</span>
            </div>
            <span className="legend-meaning">{RISK_MEANING_TH[level]}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
