/**
 * FigureFrame: a numbered figure -- "Fig. n", caption, optional source chip,
 * optional data-table disclosure and CSV download (dashboard spec §5).
 *
 * Data source: whatever the caller draws (`children`) and the numbers behind
 * it. `dataTable` is the same numbers as a table (shown on demand, so every
 * plotted point is readable without the chart); `csv` is
 * `{filename, content}` where `content` is the CSV text or a function that
 * builds it (src/lib/csv.js) only when the button is pressed.
 *
 * Numbering is the caller's (`number`): a page numbers its own figures in
 * reading order. The caption sits below the figure, as in print.
 *
 * Limitations: the CSV is built from data the page already holds; nothing is
 * fetched here. A failed download is silent apart from nothing happening;
 * the data table remains the fallback.
 */
import Icon from '../Icon.jsx'
import SourceChip from './SourceChip.jsx'
import { downloadText } from '../../lib/browser.js'
import { useLang } from '../../i18n/useLang.js'

export default function FigureFrame({
  number, caption, source, dataTable, csv, children, id, flush = false, className = '',
}) {
  const { t } = useLang()
  const hasNumber = Number.isFinite(number)
  const hasCsv = csv !== null && typeof csv === 'object' && (typeof csv.content === 'string' || typeof csv.content === 'function')

  const onCsv = () => {
    try {
      const content = typeof csv.content === 'function' ? csv.content() : csv.content
      downloadText(csv.filename, content)
    } catch {
      // Never throw from a click handler; the data table stays available.
    }
  }

  return (
    <figure className={`pw-figure ${flush ? 'pw-figure--flush' : ''} ${className}`.replace(/\s+/g, ' ').trim()} id={id}>
      <div className="pw-figure-body">{children}</div>
      <figcaption className="pw-figcaption">
        {hasNumber && <span className="pw-fig-no">{t('figure.label', { n: number })}</span>}
        <span className="pw-fig-caption">{caption}</span>
        {(source || hasCsv) && (
          <span className="pw-figure-actions">
            {source && <SourceChip source={source} />}
            {hasCsv && (
              <button type="button" className="pw-btn pw-btn--quiet pw-btn--small" onClick={onCsv}>
                <Icon name="download" size={14} strokeWidth={2} />
                {t('action.download_csv')}
              </button>
            )}
          </span>
        )}
      </figcaption>
      {dataTable && (
        <details className="pw-disclosure">
          <summary>
            <Icon name="table" size={14} strokeWidth={1.9} />
            {t('figure.view_table')}
          </summary>
          <div className="pw-disclosure-body">{dataTable}</div>
        </details>
      )}
    </figure>
  )
}
