/**
 * RunTable: the raster run provenance table of `/data` (dashboard spec
 * §4.5 item 1).
 *
 * Data source: `model` from src/lib/dataModel.js `buildRunTable`
 * (GET /raster-scan): the served run and, when the API names one, the stale
 * run. Each value carries a source button naming its field. The stale run's
 * other cells are "—" with a reason because the API returns only its id.
 *
 * Below 640 px the table becomes a list of cards (`data-label` per cell).
 * Nothing is computed here; ids and status codes are shown as sent.
 */
import SourceChip from './ui/SourceChip.jsx'
import Value from './ui/Value.jsx'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

function Cell({ column, cell }) {
  if (column.plain) {
    return (
      <span className="pw-value" data-null={cell.isNull ? 'true' : 'false'}>
        {cell.isNull ? <Value value={null} spec={cell.spec} /> : <code className="pw-mono">{cell.text}</code>}
        {cell.source && <SourceChip source={cell.source} />}
      </span>
    )
  }
  return <Value value={cell.raw} spec={cell.spec} source={cell.source ?? undefined} />
}

export default function RunTable({ model }) {
  const { t } = useLang()
  if (!model || model.rows.length === 0) return null
  return (
    <div className="pw-table-wrap">
      <table className="pw-table pw-table--stack pw-data-runs">
        <caption>{t('data.run.caption')}</caption>
        <thead>
          <tr>
            <th scope="col">{t('data.run.role_header')}</th>
            {model.columns.map((c) => <th scope="col" key={c.id}>{t(c.labelKey)}</th>)}
          </tr>
        </thead>
        <tbody>
          {model.rows.map((row) => (
            <tr key={row.key} data-role={row.role}>
              <td data-label={t('data.run.role_header')}>{t(row.role === 'stale' ? 'data.run.role_stale' : 'data.run.role_served')}</td>
              {model.columns.map((c) => (
                <td key={c.id} data-label={t(c.labelKey)} className={c.plain ? undefined : 'num'}>
                  <Cell column={c} cell={row.cells[c.id]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** The notes under the run table (no-history statement, stale note). */
export function RunNotes({ notes }) {
  const { t } = useLang()
  if (!Array.isArray(notes) || notes.length === 0) return null
  return (
    <ul className="pw-ov-notes" role="list">
      {notes.map((n, i) => <li key={`${n.key}-${i}`} data-tone={n.tone}>{renderMessage(t, n)}</li>)}
    </ul>
  )
}
