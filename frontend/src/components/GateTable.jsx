/**
 * GateTable: the switches that guard the unvalidated outputs and the
 * floors that guard the anomaly statistic, as `GET /methods` reports them
 * for this response.
 *
 * Data source: `gates.risk_evaluation_active`, `gates.signal_anomaly_active`
 * (src/scientific_status.py, read at request time) and
 * `gates.signal_anomaly_floors` (detection/src/signal_anomaly.py), through
 * src/lib/methodsModel.js `gatesModel`. Each row shows the API field name
 * (an identifier, never translated), the value exactly as returned
 * (`true`/`false`, or "—" when the response lacks it) with a plain-words
 * state, what the gate means, and a source button.
 *
 * Rules: ink only -- no colour carries the state (the word does), and no
 * risk colour is ever used. A gate's meaning text describes the switch; it
 * never claims what the water is like.
 */
import SourceChip from './ui/SourceChip.jsx'
import Value from './ui/Value.jsx'
import { useLang } from '../i18n/useLang.js'

function GateValue({ value }) {
  const { t } = useLang()
  if (value.isNull) return <Value value={null} spec={{}} source={value.source} />
  return (
    <span className="pw-value">
      <code className="pw-mono">{value.text}</code>
      <span className="pw-gate-state">{t(value.stateKey)}</span>
      <SourceChip source={value.source} />
    </span>
  )
}

export default function GateTable({ rows, floors, captionKey = 'methods.gates.caption' }) {
  const { t } = useLang()
  return (
    <div className="pw-table-wrap">
      <table className="pw-table pw-table--stack pw-gate-table">
        <caption>{t(captionKey)}</caption>
        <thead>
          <tr>
            <th scope="col">{t('methods.gates.col_field')}</th>
            <th scope="col">{t('methods.gates.col_value')}</th>
            <th scope="col">{t('methods.gates.col_meaning')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} data-gate={row.id}>
              <th scope="row" data-label={t('methods.gates.col_field')}><code className="pw-mono">{row.id}</code></th>
              <td data-label={t('methods.gates.col_value')}><GateValue value={row.value} /></td>
              <td data-label={t('methods.gates.col_meaning')}>{t(row.meaningKey)}</td>
            </tr>
          ))}
          {floors.map((row) => (
            <tr key={row.id} data-floor={row.id}>
              <th scope="row" data-label={t('methods.gates.col_field')}><code className="pw-mono">{row.value.field}</code></th>
              <td data-label={t('methods.gates.col_value')} className="num">
                <Value value={row.value.raw} spec={row.value.spec} source={row.value.source} />
              </td>
              <td data-label={t('methods.gates.col_meaning')}>{t(row.meaningKey)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
