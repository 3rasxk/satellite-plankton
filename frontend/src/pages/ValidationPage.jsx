import { useApi } from '../hooks/useApi.js'
import { getValidation } from '../api/client.js'
import { formatZ } from '../constants.js'
import SatelliteImage from '../components/SatelliteImage.jsx'

/**
 * Validation view — not named in docs/FRONTEND_PLAN.md's route table
 * (written before /validation existed on the backend); added as its own
 * route (`/validation`, linked from the nav) rather than folded into the
 * summary page, because its central fact — "0 of 14 events currently
 * matchable to a real satellite reading" — is a distinct claim from
 * either page and would get lost as a subsection. See report for this
 * choice.
 *
 * The honest baseline this page must render correctly *right now*:
 * every one of the 14 events has `matchable: false` because
 * `location_precision` is `named_site` or `province_level` on all of
 * them, never `coordinates` (CLAUDE.md/DETECTION_PLAN.md forbid
 * inventing a coordinate for a place name). This is not a loading state
 * or a bug — it's `n_matchable: 0` for real. The table below reads
 * straight from the response's counts and per-row fields, so it will
 * also render correctly, unchanged, once some events do get real
 * coordinates later.
 *
 * The "Satellite image" column follows the same rule: it renders a real
 * image only when `ev.matchable && ev.anomaly_z != null` (a real
 * satellite reading exists — see backend/src/routers/validation.py),
 * using `ev.true_color_image_url`/`ev.ndci_heatmap_image_url`, which the
 * backend itself only populates under that exact condition. All 14 rows
 * show "no satellite image available" today because 0 of them meet it
 * yet; no "5" or "7" is hardcoded anywhere in this file.
 */
export default function ValidationPage() {
  const { data, loading, error, refetch } = useApi(getValidation, [])

  return (
    <div className="page">
      <div className="page-header">
        <h1>Validation against 14 documented Thai events</h1>
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
                    <th>Anomaly z</th>
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
                      <td className="mono">
                        {ev.anomaly_z != null ? formatZ(ev.anomaly_z) : '—'}
                      </td>
                      <td className="event-image-cell">
                        {ev.matchable && ev.anomaly_z != null ? (
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
                    {row.caught === null ? 'Could not run — ' : row.caught ? 'Would have been caught — ' : 'Would have been missed — '}
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
