/**
 * SceneDateChart: how the served raster's cells split by acquisition day
 * (dashboard spec §4.2 "scene-date share bar chart").
 *
 * Data source: `GET /raster-scan` `scene_dates[]` (`date`, `cells`,
 * `share`), recorded by the run from its stored date band; arranged by
 * `buildSceneChart` (src/lib/mapModel.js). Shares are the API's own and are
 * never recomputed from the cell counts; order is the API's (largest first).
 * A bar's width is its share (layout only). Bars are ink, never a risk or
 * accent colour.
 *
 * Accessibility: the bars are decorative beside their printed percentage;
 * the figure has a text alternative (`role="img"` label listing every day)
 * and a data table (FigureFrame's disclosure) with the same numbers, plus a
 * CSV of them. A run that recorded no breakdown says so -- unknown, not
 * evenly spread.
 */
import FigureFrame from './ui/FigureFrame.jsx'
import Value from './ui/Value.jsx'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

export default function SceneDateChart({ chart, figureNumber }) {
  const { t } = useLang()
  if (!chart) return null
  if (chart.state !== 'ready') {
    return <p className="pw-map-note" data-tone="attention">{renderMessage(t, chart.empty)}</p>
  }
  const table = (
    <table className="pw-table pw-map-chart-table">
      <thead>
        <tr>
          <th scope="col">{t('map.chart.date')}</th>
          <th scope="col">{t('map.chart.share')}</th>
          <th scope="col">{t('map.chart.cells')}</th>
        </tr>
      </thead>
      <tbody>
        {chart.rows.map((row) => (
          <tr key={row.key}>
            <td className="pw-mono">{row.date}</td>
            <td><Value value={row.share.raw} spec={row.share.spec} /></td>
            <td><Value value={row.cells.raw} spec={row.cells.spec} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
  return (
    <FigureFrame
      number={figureNumber}
      caption={renderMessage(t, chart.caption)}
      source={chart.source}
      dataTable={table}
      csv={chart.csv}
      className="pw-map-chart"
    >
      <ol className="pw-map-bars" role="img" aria-label={renderMessage(t, chart.alt)}>
        {chart.rows.map((row) => (
          <li key={row.key} aria-hidden="true">
            <span className="pw-map-bar-date pw-mono">{row.date}</span>
            <span className="pw-map-bar-track">
              <span className="pw-map-bar" style={{ width: `${row.width}%` }} />
            </span>
            <span className="pw-map-bar-share pw-mono">{row.share.text}</span>
          </li>
        ))}
      </ol>
    </FigureFrame>
  )
}
