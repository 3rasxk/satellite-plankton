import { useState } from 'react'
import { useSatelliteImage } from '../hooks/useSatelliteImage.js'

// data-pipeline/src/imagery.py renders this thumbnail over a wider ~500m
// buffer for visual context, while the numeric reading next to it
// (cloud_fraction, NDCI, anomaly_z) is sampled from a tighter, clear ~30m
// buffer at the same center point (data-pipeline/src/sentinel2.py
// DEFAULT_BUFFER_M) -- this is a deliberate, documented tradeoff (see both
// modules' docstrings), not a bug: the picture and the number can
// legitimately disagree about how much cloud/turbidity is visible,
// because they're sampled over different-sized areas of the same scene.
// Always shown, not just on hover/error, so a reader never mistakes a
// clean number next to a visibly cloudy or turbid picture for a
// contradiction.
const BUFFER_CAVEAT_TEXT =
  "This image shows a wider ~500m area for visual context. The numeric reading " +
  '(cloud fraction, NDCI, anomaly) is sampled from a smaller, clear ~30m area at ' +
  "the center, and may not reflect everything visible in the wider image — clouds " +
  "or turbidity outside the sampled area won't affect the number."

/**
 * Renders a satellite image fetched from a relative backend URL
 * (`/satellite-image?...` or `/risk-map/{site_id}/image?...`), with a
 * toggle between true-colour and NDCI heatmap renders when both are
 * available for the current point. `null` URLs mean the caller already
 * determined there is no usable scene (status != 'ok', no cached image,
 * no matched validation event) — this renders the same
 * `.status-banner` "no imagery" pattern the rest of the app already uses
 * for non-'ok' statuses, never a placeholder picture (CLAUDE.md: never
 * fabricate).
 */
export default function SatelliteImage({
  trueColorUrl,
  ndciHeatmapUrl,
  noImageMessage,
  caption,
  compact = false,
}) {
  const hasBoth = !!trueColorUrl && !!ndciHeatmapUrl

  // `userMode` is only the viewer's explicit toggle choice, or null if
  // they haven't clicked one yet. The effective mode is derived at
  // render time rather than reconciled in an effect: if the user's
  // chosen type has no URL for the current site/date (e.g. they picked
  // NDCI, then a new selection only has true-colour), it falls back to
  // whichever type does have a URL, without a stale intermediate render.
  const [userMode, setUserMode] = useState(null)
  const mode =
    userMode === 'true_color' && trueColorUrl
      ? 'true_color'
      : userMode === 'ndci_heatmap' && ndciHeatmapUrl
        ? 'ndci_heatmap'
        : trueColorUrl
          ? 'true_color'
          : 'ndci_heatmap'

  const activeUrl = mode === 'true_color' ? trueColorUrl : ndciHeatmapUrl
  const { loading, error, objectUrl } = useSatelliteImage(activeUrl)

  if (!trueColorUrl && !ndciHeatmapUrl) {
    return (
      <div className="status-banner satellite-no-image">
        <strong>No satellite image available</strong>
        <p>{noImageMessage || 'No usable satellite scene for this point/date.'}</p>
      </div>
    )
  }

  return (
    <div className={`satellite-image-block${compact ? ' compact' : ''}`}>
      {hasBoth && (
        <div className="satellite-toggle" role="group" aria-label="Satellite image type">
          <button
            type="button"
            className={mode === 'true_color' ? 'active' : ''}
            onClick={() => setUserMode('true_color')}
          >
            True colour
          </button>
          <button
            type="button"
            className={mode === 'ndci_heatmap' ? 'active' : ''}
            onClick={() => setUserMode('ndci_heatmap')}
          >
            NDCI heatmap
          </button>
        </div>
      )}

      <div className="satellite-image-frame">
        {loading && <p className="no-rules">Rendering satellite image&hellip; this can take several seconds.</p>}
        {error && (
          <div className="status-banner">
            <strong>Image unavailable</strong>
            <p>{error}</p>
          </div>
        )}
        {!loading && !error && objectUrl && (
          <img
            className="satellite-image"
            src={objectUrl}
            alt={mode === 'true_color' ? 'True-colour Sentinel-2 image' : 'NDCI heatmap of chlorophyll anomaly'}
          />
        )}
      </div>

      {caption && !loading && !error && objectUrl && <p className="satellite-caption">{caption}</p>}

      <p className="satellite-buffer-caveat">{BUFFER_CAVEAT_TEXT}</p>
    </div>
  )
}
