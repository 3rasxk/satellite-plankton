/**
 * OverviewMapPreview: the Overview's map figure -- the served NDCI overlay
 * PNG on its own bounds, the monitoring sites for orientation, the pins of
 * the same run, a legend and the pin list (dashboard spec §4.1 item 3,
 * §4.6; test-baseline spec §6).
 *
 * Data source: `model.preview` from src/lib/overviewModel.js, i.e.
 *   - `GET /raster-scan`: overlay_url (fetched through apiAssetUrl),
 *     bounds, legend swatches/domain, run and scene dates;
 *   - `GET /raster-scan/highlights?n=5&run_id=<run shown>`: pins, mode;
 *   - `GET /risk-map`: site coordinates.
 *
 * A bounds-fitted figure, not a Leaflet map: the overlay is a regular
 * latitude-longitude grid (backend OverlayGrid, row 0 north), so a box with
 * the bounds' aspect ratio and the image stretched to it is the raster's
 * own geometry, and a pin goes at its percentage position. No tiles, no
 * network beyond the one PNG, printable, and nothing to pan or zoom by
 * accident while scrolling. The full map is one link away (/map).
 *
 * Rules: colours are the API's swatches only (hex-validated in the model);
 * pins are dark-neutral numbered marks -- a square for "highest NDCI in
 * this scan", a diamond for TEST anomaly pins -- never a risk colour and
 * never the interaction accent; sites are hollow circles. Transparent
 * pixels stay transparent over a neutral ground: not measured is not low.
 * If the PNG fails to download the figure says so, so a blank box is never
 * read as "nothing measured".
 */
import { useId, useState } from 'react'
import Icon from './Icon.jsx'
import EmptyState from './ui/EmptyState.jsx'
import ErrorState from './ui/ErrorState.jsx'
import FigureFrame from './ui/FigureFrame.jsx'
import RouteLink from './ui/RouteLink.jsx'
import StatusChip from './ui/StatusChip.jsx'
import Value from './ui/Value.jsx'
import { chipForStatus, STATUS } from '../lib/statusChip.js'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

const pct = (v) => `${v.toFixed(3)}%`

/** A compact error line for a block inside a card (the figure keeps the
 * full ErrorState). */
export function InlineError({ message, error, onRetry }) {
  const { t } = useLang()
  const status = error?.error?.response?.status
  return (
    <div className="pw-ov-error" role="status">
      <p>{renderMessage(t, message)}</p>
      <p className="pw-state-facts">
        {Number.isInteger(status) && <span className="pw-mono">{t('error.http', { status })}</span>}
        {error?.endpoint && (
          <span>{t('error.request')}: <code className="pw-mono">{`GET ${error.endpoint}`}</code></span>
        )}
      </p>
      {typeof onRetry === 'function' && (
        <button type="button" className="pw-btn pw-btn--quiet pw-btn--small" onClick={() => onRetry()}>
          <Icon name="refresh" size={14} strokeWidth={2} />
          {t('common.retry')}
        </button>
      )}
    </div>
  )
}

function ServerText({ labelKey, text }) {
  const { t } = useLang()
  if (!text) return null
  return (
    <>
      <p className="pw-label pw-ov-server-label">{t(labelKey)}</p>
      <blockquote className="pw-server-text" lang="en">{text}</blockquote>
    </>
  )
}

function Legend({ legend, showSites }) {
  const { t } = useLang()
  const headingId = useId()
  return (
    <section className="pw-card pw-ov-legend" aria-labelledby={headingId}>
      <h3 className="pw-card-title" id={headingId}>{t('overview.map.legend_heading')}</h3>
      <p className="pw-ov-legend-title">{t('overview.map.legend_ndci')}</p>
      {legend.swatches.length > 0 && (
        <div className="pw-ov-ramp" aria-hidden="true">
          {legend.swatches.map((s, i) => <span key={`${i}-${s.hex}`} style={{ background: s.hex }} />)}
        </div>
      )}
      {(legend.min || legend.max) && (
        <div className="pw-ov-ramp-scale pw-mono">
          <span>{legend.min}</span>
          <span>{legend.max}</span>
        </div>
      )}
      <ul className="pw-ov-keys" role="list">
        <li>
          <span className="pw-ov-key-nodata" aria-hidden="true" />
          <span>{t('overview.map.legend_no_data')}</span>
        </li>
        {showSites && (
          <li>
            <span className="pw-ov-key-site" aria-hidden="true" />
            <span>{t('overview.map.legend_site')}</span>
          </li>
        )}
      </ul>
      {legend.serverMeaning && (
        <details className="pw-disclosure pw-ov-legend-server">
          <summary>{t('overview.map.server_meaning')}</summary>
          <div className="pw-disclosure-body">
            <blockquote className="pw-server-text" lang="en">{legend.serverMeaning}</blockquote>
          </div>
        </details>
      )}
    </section>
  )
}

function PinBadge({ shape, rank, className }) {
  return (
    <span className={className} data-shape={shape} aria-hidden="true">
      <span>{rank}</span>
    </span>
  )
}

function PinList({ pins, onRetry }) {
  const { t } = useLang()
  const say = (m) => renderMessage(t, m)
  const headingId = useId()
  let body
  if (pins.state === 'loading') {
    body = <p className="pw-ov-loading" aria-busy="true">{t('overview.state.pins_loading')}</p>
  } else if (pins.state === 'error') {
    body = <InlineError message={{ key: 'overview.state.pins_error', params: {} }} error={pins.error} onRetry={onRetry} />
  } else if (pins.state !== 'ready') {
    body = (
      <>
        <p className="pw-ov-pins-empty">{say(pins.empty)}</p>
        <ServerText labelKey="overview.server_reason" text={pins.serverReason} />
      </>
    )
  } else {
    body = (
      <>
        <p className="pw-ov-pins-legend">
          <PinBadge shape={pins.shape} rank="1" className="pw-ov-pin-key" />
          <span>{t(pins.legendKey)}</span>
        </p>
        <ol className="pw-ov-pin-list" role="list">
          {pins.items.map((p) => (
            <li key={p.rank} data-pin={p.rank}>
              <PinBadge shape={pins.shape} rank={p.rank} className="pw-ov-pin-badge" />
              <div className="pw-ov-pin-body">
                <p className="pw-ov-pin-values">
                  <span className="pw-sr-only">{`${t('overview.pins.rank')} ${p.rank}: `}</span>
                  <span className="pw-ov-pin-field">
                    <span className="pw-label">NDCI</span>
                    <Value value={p.ndci.raw} spec={p.ndci.spec} source={p.source} />
                  </span>
                  {p.z && (
                    <span className="pw-ov-pin-field">
                      <span className="pw-label">{t('overview.pins.z')}</span>
                      <Value value={p.z.raw} spec={p.z.spec} source={p.zSource} />
                    </span>
                  )}
                  {p.chip && <StatusChip chip={p.chip} />}
                </p>
                <p className="pw-ov-pin-meta">
                  <Value value={p.date.raw} spec={p.date.spec} />
                  {p.edge && <span className="pw-ov-pin-edge">{t('overview.pins.edge')}</span>}
                  <RouteLink to={p.href} aria-label={t('overview.pins.open', { rank: p.rank })}>
                    {t('overview.pins.open_short')}
                  </RouteLink>
                </p>
              </div>
            </li>
          ))}
        </ol>
        {pins.notes.length > 0 && (
          <ul className="pw-ov-notes" role="list">
            {pins.notes.map((n) => <li key={n.key} data-tone={n.tone}>{say(n)}</li>)}
          </ul>
        )}
        <ServerText labelKey="overview.server_reason" text={pins.serverReason} />
        <p className="pw-ov-caveat">{t('overview.pins.caveat')}</p>
      </>
    )
  }
  return (
    <section className="pw-card pw-ov-pins" aria-labelledby={headingId} data-state={pins.state} data-mode={pins.mode ?? undefined}>
      <h3 className="pw-card-title" id={headingId}>{t(pins.headingKey)}</h3>
      {body}
    </section>
  )
}

export default function OverviewMapPreview({ preview, figureNumber = 1, onRetry, onRetryPins }) {
  const { t } = useLang()
  const say = (m) => renderMessage(t, m)
  // Keyed by URL, so a new run's image gets a fresh chance to load.
  const [failedUrl, setFailedUrl] = useState(null)

  if (preview.state === 'loading') {
    return (
      <div className="pw-ov-map-loading" aria-busy="true">
        <div className="pw-ov-map-skeleton" aria-hidden="true" />
        <p className="pw-ov-loading">{t('overview.state.raster_loading')}</p>
      </div>
    )
  }
  if (preview.state === 'error') {
    return (
      <ErrorState
        error={preview.error?.error}
        endpoint={preview.error?.endpoint}
        onRetry={onRetry}
        title={t('overview.state.raster_error')}
        level={3}
      />
    )
  }
  if (preview.state === 'empty') {
    return <EmptyState level={3} icon="map" title={t('overview.state.map_empty_title')} body={say(preview.empty)} />
  }

  const pins = preview.pins
  const drawn = pins.state === 'ready' ? pins.items.filter((p) => p.inFigure) : []
  const imageFailed = failedUrl === preview.image.url
  const caption = (
    <>
      {say(preview.caption)}
      {' '}
      <span className="pw-ov-extent">{`${t('overview.map.extent_label')}: ${say(preview.extent)}`}</span>
    </>
  )

  return (
    <div className="pw-grid pw-ov-map-grid">
      <div className="pw-span-7 pw-ov-map-main">
        <FigureFrame number={figureNumber} caption={caption} source={preview.source} csv={pins.csv}>
          <div
            className="pw-ov-map"
            style={{ aspectRatio: String(preview.box.aspect) }}
            role="img"
            aria-label={say(preview.image.alt)}
            data-state={preview.state}
          >
            {!imageFailed && (
              <img
                className="pw-ov-map-img"
                src={preview.image.url}
                alt=""
                decoding="async"
                onError={() => setFailedUrl(preview.image.url)}
              />
            )}
            {preview.sites.map((s) => (
              <span key={s.id} className="pw-ov-site" style={{ left: pct(s.x), top: pct(s.y) }} title={s.name} aria-hidden="true" />
            ))}
            {drawn.map((p) => (
              <span
                key={p.rank}
                className="pw-ov-pin"
                data-shape={pins.shape}
                style={{ left: pct(p.x), top: pct(p.y) }}
                aria-hidden="true"
              >
                <span>{p.rank}</span>
              </span>
            ))}
          </div>
          {imageFailed && <p className="pw-ov-image-error" role="status">{t('overview.map.image_error')}</p>}
        </FigureFrame>
        {preview.staleNote && (
          <p className="pw-ov-stale">
            <StatusChip chip={chipForStatus(STATUS.STALE)} />
            <span>{say(preview.staleNote)}</span>
          </p>
        )}
        <RouteLink to="/map" className="pw-btn pw-btn--quiet pw-btn--small pw-ov-map-link">
          {t('overview.open_map')}
          <Icon name="arrow-right" size={14} strokeWidth={2} />
        </RouteLink>
      </div>
      <div className="pw-span-5 pw-ov-map-aside">
        <Legend legend={preview.legend} showSites={preview.sites.length > 0} />
        <PinList pins={pins} onRetry={onRetryPins} />
      </div>
    </div>
  )
}
