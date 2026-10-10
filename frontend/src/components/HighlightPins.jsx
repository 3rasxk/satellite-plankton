/**
 * HighlightPins: the numbered pins on the raster map, and PinDetails, the
 * inspector view of one pin (dashboard spec §4.6; test-baseline spec §6).
 *
 * Data source: `GET /raster-scan/highlights?n=<3-10>&run_id=<served run>`
 * -- the API picks the mode (no `mode` is sent): 'ndci' ranks the run's
 * measured cells by NDCI within this one image; 'anomaly' pins cells at or
 * over the TEST anomaly condition against their own seasonal history. View
 * models: `buildPinsModel` / `buildPinView` (src/lib/mapModel.js).
 *
 * Markers: Leaflet divIcons -- dark neutral, numbered, a square (NDCI) or a
 * diamond (TEST anomaly); never a risk colour, never the accent (only the
 * selected pin's focus ring uses it, as interaction). A marker sits on the
 * centre of the overlay square its cell paints (`pixel_centre_*`); the
 * inspector also gives the observation's own coordinate (`cell_*`).
 * Markers are Leaflet Markers, whose clicks do not bubble to the map
 * (`bubblingMouseEvents: false`), so picking a pin never also reads the
 * cell under it. No code path here reads `risk_tier`.
 *
 * Limitations: a marker is only drawn for a pin with a finite position; the
 * rail lists every pin.
 */
import L from 'leaflet'
import { Marker } from 'react-leaflet'
import Icon from './Icon.jsx'
import { InspectorActions } from './RasterPixelPanel.jsx'
import { CountsBlock } from './PinList.jsx'
import PinLegend from './PinLegend.jsx'
import RouteLink from './ui/RouteLink.jsx'
import StatusChip from './ui/StatusChip.jsx'
import Value from './ui/Value.jsx'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

const ICON_PX = 26
const icons = new Map()

/** One cached divIcon per (rank, shape, selected): a new icon object on
 * every render would make Leaflet rebuild the marker element and drop focus. */
function pinIcon(rank, shape, selected) {
  const key = `${rank}|${shape}|${selected ? 1 : 0}`
  if (!icons.has(key)) {
    const n = Number.isInteger(rank) ? rank : 0
    const safeShape = shape === 'diamond' ? 'diamond' : 'square'
    icons.set(key, L.divIcon({
      className: 'pw-map-pin-wrap',
      html: `<span class="pw-map-pin" data-shape="${safeShape}"${selected ? ' data-selected="true"' : ''}><span>${n}</span></span>`,
      iconSize: [ICON_PX, ICON_PX],
      iconAnchor: [ICON_PX / 2, ICON_PX / 2],
    }))
  }
  return icons.get(key)
}

export default function HighlightPins({ pins, selectedRank = null, onSelect }) {
  const { t } = useLang()
  if (!pins || pins.state !== 'ready' || pins.show === false) return null
  return pins.items.filter((p) => p.onMap).map((p) => {
    const selected = p.rank === selectedRank
    return (
      <Marker
        key={p.rank}
        position={[p.lat, p.lng]}
        icon={pinIcon(p.rank, pins.shape, selected)}
        title={t('map.pins.marker', { rank: p.rank })}
        keyboard
        bubblingMouseEvents={false}
        zIndexOffset={selected ? 1000 : 0}
        eventHandlers={{ click: () => onSelect?.(p.rank) }}
      />
    )
  })
}

function Field({ label, value, source, children }) {
  return (
    <div className="pw-map-field">
      <dt>{label}</dt>
      <dd>
        {value && <Value value={value.raw} spec={value.spec} source={source} />}
        {children}
      </dd>
    </div>
  )
}

function Coordinate({ label, coord }) {
  return (
    <div className="pw-map-field">
      <dt>{label}</dt>
      <dd>
        <Value value={coord.lat.raw} spec={coord.lat.spec} />
        {', '}
        <Value value={coord.lng.raw} spec={coord.lng.spec} source={coord.source} />
      </dd>
    </div>
  )
}

/**
 * The inspector for one pin.
 * @param {{view, onClose, onZoom, onInspect, citation, permalink}} props
 *   `view` from buildPinView; `onZoom()` flies to the pin; `onInspect()`
 *   reads the pin's cell through /raster-scan/pixel.
 */
export function PinDetails({ view, onClose, onZoom, onInspect, citation, permalink }) {
  const { t } = useLang()
  if (!view) return null
  return (
    <div className="raster-pixel-panel glass pw-map-pin-panel" role="region" aria-label={renderMessage(t, view.title)} data-mode={view.mode ?? undefined}>
      <div className="raster-pixel-head">
        <span className="raster-pixel-title">{renderMessage(t, view.title)}</span>
        {onClose && (
          <button type="button" className="raster-pixel-close" onClick={onClose} aria-label={t('common.close')}>
            ×
          </button>
        )}
      </div>
      <p className="pw-map-pin-panel-kind">{t(view.headingKey)}</p>
      <PinLegend mode={view.mode} />

      <p className="pw-label">{t('map.pin.indices')}</p>
      <dl className="raster-pixel-values">
        {view.indices.map((row) => (
          <div className="raster-pixel-value" key={row.id}>
            <dt><RouteLink to={row.href} className="pw-map-index-link">{row.label}</RouteLink></dt>
            <dd className="mono"><Value value={row.value.raw} spec={row.value.spec} source={row.source} /></dd>
          </div>
        ))}
      </dl>

      {view.anomaly && (
        <section className="pw-map-block pw-map-test-block" data-test-block="true">
          <h3 className="pw-map-block-title">{t('map.anomaly.heading')}</h3>
          <p className="pw-map-chips"><StatusChip chip={view.anomaly.chip} /></p>
          <dl className="pw-map-fields">
            {view.anomaly.rows.map((row) => (
              <Field key={row.id} label={t(row.labelKey)} value={row.value} source={row.source} />
            ))}
            <Field label={t('map.anomaly.season_key')}><code className="pw-mono">{view.anomaly.seasonKey}</code></Field>
            <Field label={t('map.anomaly.baseline_version')}><code className="pw-mono">{view.anomaly.baselineVersion}</code></Field>
          </dl>
          <p className="pw-map-note">{t('map.anomaly.note')}</p>
        </section>
      )}

      <dl className="pw-map-fields">
        <Field label={t('map.pin.percentile')} value={view.percentile.value} source={view.percentile.source} />
      </dl>
      <p className="pw-map-note">{renderMessage(t, view.percentile.note)}</p>

      <dl className="pw-map-fields">
        <Field label={t('map.pin.acquired_date')} value={view.acquiredDate.value} source={view.acquiredDate.source} />
        <Field label={t('map.pin.acquired_at')} value={view.acquiredAt.value} source={view.acquiredAt.source} />
        <Coordinate label={t('map.pin.cell')} coord={view.cell} />
        <Coordinate label={t('map.pin.centre')} coord={view.centre} />
        <Field label={t('common.run')}><code className="pw-mono">{view.runId}</code></Field>
      </dl>

      <p className="pw-map-note" data-tone={view.edge.tone}>{renderMessage(t, view.edge)}</p>

      <p className="pw-label">{t('map.pin.bands')}</p>
      {view.bands ? (
        <dl className="pw-map-fields pw-map-fields--3">
          {view.bands.map((b) => <Field key={b.id} label={t(b.labelKey)} value={b.value} source={b.source} />)}
        </dl>
      ) : (
        <p className="pw-map-note">{t('map.pin.bands_none')}</p>
      )}

      <p className="pw-map-note pw-map-caveat">{t(view.caveatKey)}</p>
      <p className="pw-map-note">{renderMessage(t, view.separation)}</p>
      {view.ranking && (
        <div className="pw-map-server">
          <p className="pw-label">{t('map.pin.ranking')}</p>
          <blockquote className="pw-server-text" lang="en">{view.ranking}</blockquote>
        </div>
      )}

      <CountsBlock counts={view.counts} open />

      {view.disclaimer && (
        <div className="pw-map-server">
          <p className="pw-label">{t('map.pin.disclaimer')}</p>
          <blockquote className="pw-server-text" lang="en">{view.disclaimer}</blockquote>
        </div>
      )}

      <InspectorActions
        citation={citation}
        permalink={permalink}
        csv={{ ...view.csv, labelKey: 'map.pin.csv_row' }}
        rawUrl={view.rawUrl}
      >
        {view.target && onZoom && (
          <button type="button" className="pw-btn pw-btn--quiet pw-btn--small" onClick={() => onZoom()}>
            <Icon name="map" size={14} strokeWidth={2} />
            {t('map.pin.zoom')}
          </button>
        )}
        {view.cellQuery && onInspect && (
          <button type="button" className="pw-btn pw-btn--quiet pw-btn--small" onClick={() => onInspect()}>
            <Icon name="source" size={14} strokeWidth={2} />
            {t('map.pin.inspect')}
          </button>
        )}
      </InspectorActions>
    </div>
  )
}
