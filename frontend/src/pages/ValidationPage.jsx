import { useApi } from '../hooks/useApi.js'
import { getValidation } from '../api/client.js'
import { ANOMALY_NOT_COMPUTED } from '../constants.js'
import SatelliteImage from '../components/SatelliteImage.jsx'

/**
 * Validation view — its own route (`/validation`, linked from the nav)
 * rather than a section of the summary page, because what this set is
 * and is not is a distinct claim that would get lost as a subsection.
 *
 * The page is fully data-driven: every count and row comes from
 * /validation, so it renders correctly as the underlying numbers change
 * and has needed no edit as they have. What it must never do is present
 * this set as a pass/fail gate. 7 of the 14 events carry a real
 * coordinate; 1 (th_010, Ang Sila) has produced a real satellite
 * reading. Neither number is a score — see LIMITATIONS.md §1 for why
 * that single reading is not evidence in either direction.
 *
 * The "Satellite image" column follows the same rule: it renders a real
 * image only when `ev.reading_status === 'ok'` (a real
 * satellite reading exists independently of anomaly scoring),
 * using `ev.true_color_image_url`/`ev.ndci_heatmap_image_url`, which the
 * backend itself only populates under that exact condition. No count is
 * hardcoded anywhere in this file.
 */
export default function ValidationPage() {
  const { data, loading, error, refetch } = useApi(getValidation, [])

  return (
    <div className="page">
      <div className="page-header">
        <h1>The 14 documented Thai events</h1>
        <span className="updated-line">
          {data ? `Calibration status: ${data.calibration_status}` : 'Leave-one-out calibration attempt'}
        </span>
      </div>

      {loading && (
        <div className="state-panel">
          <h3>Loading validation table…</h3>
        </div>
      )}

      {error && (
        <div className="state-panel error">
          <h3>Couldn&apos;t reach the data service. Retry.</h3>
          <button type="button" className="retry-btn" onClick={refetch}>Retry</button>
        </div>
      )}

      {data && (
        <>
          <div className="validation-callout">
            <span className="headline">
              {data.n_matchable} of {data.n_events} events currently have a coordinate precise enough to match a satellite reading
            </span>
            <p>{data.calibration_caveat}</p>
            <div className="match-counts">
              <div className="match-count">
                <span className="n mono">{data.n_events}</span>
                <span className="label">Documented events</span>
              </div>
              <div className="match-count">
                <span className="n mono">{data.n_matchable}</span>
                <span className="label">With a usable coordinate</span>
              </div>
              <div className="match-count">
                <span className="n mono">{data.n_with_real_satellite_reading}</span>
                <span className="label">With a real satellite reading</span>
              </div>
            </div>
          </div>

          <section className="summary-section">
            <div className="section-title">All 14 events</div>
            <div className="table-scroll">
              <table className="events-table">
                <thead>
                  <tr>
                    <th>Event</th>
                    <th>Date</th>
                    <th>Location</th>
                    <th>Precision</th>
                    <th>Species</th>
                    <th>Cell count</th>
                    <th>Match</th>
                    <th>Anomaly status</th>
                    <th>Actual scene date</th>
                    <th>Satellite image</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {data.events.map((ev) => (
                    <tr key={ev.event_id}>
                      <td className="mono">
                        {ev.event_id}
                        {ev.low_evidentiary_weight && (
                          <div className="low-weight-flag">low evidentiary weight</div>
                        )}
                      </td>
                      <td className="mono">{ev.date_display}</td>
                      <td>{ev.location_name}</td>
                      <td className="mono">{ev.location_precision}</td>
                      <td>{ev.species}</td>
                      <td className="mono">
                        {ev.cell_count_raw || (ev.cell_count_representative != null ? ev.cell_count_representative : '—')}
                      </td>
                      <td>
                        <span className={`match-badge${ev.matchable ? ' matched' : ''}`}>
                          {ev.matchable ? ev.match_method || 'matched' : 'not matched'}
                        </span>
                        {ev.match_reason && (
                          <div className="stat-detail" style={{ marginTop: 4 }}>{ev.match_reason}</div>
                        )}
                      </td>
                      <td>{ANOMALY_NOT_COMPUTED}</td>
                      <td className="mono">{ev.actual_date || '—'}</td>
                      <td className="event-image-cell">
                        {ev.reading_status === 'ok' ? (
                          <SatelliteImage
                            trueColorUrl={ev.true_color_image_url}
                            ndciHeatmapUrl={ev.ndci_heatmap_image_url}
                            noImageMessage="No satellite image available for this event."
                            compact
                          />
                        ) : (
                          <span className="no-rules">No satellite image available for this event.</span>
                        )}
                      </td>
                      <td>{ev.notes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="summary-section">
            <div className="section-title">Leave-one-out calibration attempt ({data.leave_one_out.length} iterations)</div>
            <ul className="loo-list">
              {data.leave_one_out.map((row) => (
                <li key={row.iteration_label}>
                  <span className="loo-label mono">
                    {row.iteration_label} — held out: {row.held_out_event_ids.join(', ')}
                  </span>
                  <span>
                    {row.caught === null ? 'Cannot be evaluated — ' : row.caught ? 'Would have been caught — ' : 'Would have been missed — '}
                    {row.reason}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
