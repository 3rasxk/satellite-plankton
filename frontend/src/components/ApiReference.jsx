/**
 * ApiReference: the endpoints the dashboard uses, each with a link to the
 * live example, the response schema (backend/src/schemas.py) and the fields
 * the interface reads from it (dashboard spec §4.5 item 3).
 *
 * Data source: `rows` from src/lib/dataModel.js `buildApiReference`
 * (static metadata; tests/data_model.test.js checks every field against
 * schemas.py and every path against the router files). Nothing is fetched.
 *
 * Below 640 px the table becomes a list of cards.
 */
import RouteLink from './ui/RouteLink.jsx'
import { useLang } from '../i18n/useLang.js'

export default function ApiReference({ rows }) {
  const { t } = useLang()
  return (
    <div className="pw-table-wrap">
      <table className="pw-table pw-table--stack pw-data-api">
        <caption>{t('data.api.caption')}</caption>
        <thead>
          <tr>
            <th scope="col">{t('data.api.col_endpoint')}</th>
            <th scope="col">{t('data.api.col_example')}</th>
            <th scope="col">{t('data.api.col_schema')}</th>
            <th scope="col">{t('data.api.col_fields')}</th>
            <th scope="col">{t('data.api.col_used_by')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} data-endpoint={row.id}>
              <td data-label={t('data.api.col_endpoint')}>
                <code className="pw-mono">{row.path}</code>
                <span className="pw-data-ep-note">{t(row.labelKey)}</span>
              </td>
              <td data-label={t('data.api.col_example')}>
                <a href={row.href} target="_blank" rel="noopener noreferrer" className="pw-mono pw-data-example">
                  {row.example}
                </a>
                <span className="pw-sr-only">{` (${t('data.api.open')})`}</span>
              </td>
              <td data-label={t('data.api.col_schema')}>
                {row.schema
                  ? <code className="pw-mono">{row.schema}</code>
                  : <span>{t(row.image ? 'data.api.image' : 'data.api.no_schema')}</span>}
              </td>
              <td data-label={t('data.api.col_fields')}>
                <ul className="pw-data-fields" role="list">
                  {row.fields.map((f) => <li key={f}><code className="pw-mono">{f}</code></li>)}
                </ul>
              </td>
              <td data-label={t('data.api.col_used_by')}>
                <ul className="pw-data-used" role="list">
                  {row.usedBy.map((p) => <li key={p.id}><RouteLink to={p.to}>{t(p.labelKey)}</RouteLink></li>)}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
