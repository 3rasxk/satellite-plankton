/**
 * SitesTable: the seven monitoring sites as a sortable table (dashboard spec
 * §4.3), a card list below 640 px.
 *
 * Data source: `model` from src/lib/sitesModel.js `buildSitesModel` (GET
 * /risk-map): rows of formatted values with source refs, status chips and
 * the TEST anomaly cell, the visible columns and the sort state. Nothing is
 * computed here.
 *
 * Interaction: every column header is a real <button> (keyboard operable;
 * the header's `aria-sort` states the order) followed by a source popover
 * naming the endpoint, field path, unit and meaning of the column. Unknown
 * values sort last in both directions (model). Below 640 px the header row
 * is visually hidden, each row becomes a card whose cells carry their
 * column name (`data-label`), and a "Sort by" select replaces the header
 * buttons.
 *
 * Rules: a "—" always carries its reason (the site's status, the server's
 * error text verbatim, or `signal_anomaly_reason`); anomaly chips appear
 * only as the model allows (valid TEST baseline, non-null level) and always
 * say "(TEST)"; no risk tier and no risk colour.
 */
import { useId } from 'react'
import Icon from './Icon.jsx'
import RouteLink from './ui/RouteLink.jsx'
import SourceChip from './ui/SourceChip.jsx'
import StatusChip from './ui/StatusChip.jsx'
import Value from './ui/Value.jsx'
import { ariaSort, columnSource, nextSort } from '../lib/sitesModel.js'
import { reasonKey } from '../lib/format.js'
import { useLang } from '../i18n/useLang.js'

function columnLabel(column, t) {
  return typeof column.label === 'string' ? column.label : t(column.labelKey)
}

/** The reason text of a code (i18n when known, else the API code verbatim). */
function reasonText(code, t) {
  const key = reasonKey(code)
  return key ? t(key) : code
}

function SortGlyph({ state }) {
  const name = state === 'ascending' ? 'sort-asc' : state === 'descending' ? 'sort-desc' : 'sort'
  return <Icon name={name} size={14} strokeWidth={2} className="pw-sort-icon" />
}

function Cell({ column, row }) {
  const { t } = useLang()
  const id = column.id
  switch (id) {
    case 'name':
      return <RouteLink to={row.href} className="pw-sites-name" lang="en">{row.name}</RouteLink>
    case 'status':
      return (
        <>
          <span className="pw-chips">{row.chips.map((c) => <StatusChip key={c.key} chip={c} />)}</span>
          {row.status !== 'ok' && (
            <span className="pw-sites-reason">
              {reasonText(row.nullReason, t)}
              {row.nullReasonText && <span className="pw-server-inline" lang="en">{` ${row.nullReasonText}`}</span>}
            </span>
          )}
        </>
      )
    case 'index_used':
      return row.indexUsed
        ? <span className="pw-value"><code className="pw-mono">{row.indexUsed}</code><SourceChip source={row.sources.index_used} /></span>
        : <Value value={null} spec={{ reason: row.nullReason }} reasonText={row.nullReasonText ?? undefined} source={row.sources.index_used} />
    case 'stale':
      return (
        <span className="pw-value">
          <span>{t(row.stale ? 'common.yes' : 'common.no')}</span>
          <SourceChip source={row.sources.stale} />
        </span>
      )
    case 'anomaly':
      if (row.anomaly.shown) {
        return (
          <span className="pw-sites-anomaly">
            <StatusChip chip={row.anomaly.chip} />
            <span className="pw-sites-z">
              <span className="pw-label">{t('sites.z_label')}</span>
              <Value value={row.anomaly.z.raw} spec={row.anomaly.z.spec} source={row.anomaly.zSource} />
            </span>
          </span>
        )
      }
      return <Value value={null} spec={row.anomaly.z.spec} source={row.anomaly.levelSource} showReason />
    default: {
      const cell = row.cells[id]
      if (!cell) return null
      return (
        <Value
          value={cell.raw}
          spec={cell.spec}
          source={row.sources[id]}
          reasonText={cell.isNull && row.nullReasonText ? row.nullReasonText : undefined}
        />
      )
    }
  }
}

export default function SitesTable({ model, onSort }) {
  const { t } = useLang()
  const selectId = useId()
  const sort = model.sort
  const columns = model.columns
  const sortable = typeof onSort === 'function'
  const activate = (columnId) => {
    if (sortable) onSort(nextSort(sort, columnId))
  }

  return (
    <div className="pw-sites">
      {sortable && (
        <div className="pw-sites-sort-mobile">
          <label htmlFor={selectId} className="pw-label">{t('sites.sort_by')}</label>
          <select
            id={selectId}
            className="pw-select"
            value={sort ? sort.column : ''}
            onChange={(event) => onSort(event.target.value ? { column: event.target.value, direction: sort?.direction ?? 'asc' } : null)}
          >
            <option value="">{t('sites.sort_default')}</option>
            {columns.map((c) => <option key={c.id} value={c.id}>{columnLabel(c, t)}</option>)}
          </select>
          {sort && (
            <button
              type="button"
              className="pw-btn pw-btn--small"
              onClick={() => onSort({ column: sort.column, direction: sort.direction === 'asc' ? 'desc' : 'asc' })}
            >
              <SortGlyph state={sort.direction === 'desc' ? 'descending' : 'ascending'} />
              {t(sort.direction === 'desc' ? 'sites.sort_desc' : 'sites.sort_asc')}
            </button>
          )}
        </div>
      )}
      <div className="pw-table-wrap pw-sites-wrap">
        <table className="pw-table pw-table--stack pw-sites-table">
          <caption>
            {t('sites.table_caption', { endpoint: 'GET /risk-map' })}
            <span className="pw-sites-caption-note">{t('sites.unknown_last')}</span>
          </caption>
          <thead>
            <tr>
              {columns.map((c) => {
                const state = ariaSort(sort, c.id)
                const label = columnLabel(c, t)
                return (
                  <th key={c.id} scope="col" aria-sort={state} className={c.num ? 'num' : undefined} data-col={c.id}><button
                    type="button"
                    className="pw-sort-btn"
                    onClick={() => activate(c.id)}
                    disabled={!sortable}
                    aria-label={t('sites.sort_button', { column: label })}
                  >
                    <span>{label}</span>
                    <SortGlyph state={state} />
                  </button><SourceChip source={columnSource(c)} headingKey="sites.source.column_heading" /></th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {model.rows.map((row) => (
              <tr key={row.id} data-site={row.id} data-status={row.status ?? 'unknown'}>
                {columns.map((c) => (
                  <td key={c.id} data-label={columnLabel(c, t)} data-col={c.id} className={c.num ? 'num' : undefined}>
                    <Cell column={c} row={row} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
