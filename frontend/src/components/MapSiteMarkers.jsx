/**
 * MapSiteMarkers: the seven fixed monitoring stations on the raster map --
 * a white-ringed circle with a small glass label chip "Name · status".
 *
 * Data source: `items` of src/lib/mapListModel.js `buildSiteListModel` over
 * `GET /risk-map` (the scheduler's cached readings; no Earth Engine call).
 *
 * Markers (no colour carries data; shape and fill do):
 *   - 'reading'     dark neutral filled circle, white ring;
 *   - 'no_data'     hollow circle with a dashed grey ring (no usable reading);
 *   - 'not_checked' hollow circle with a dotted grey ring;
 *   - selected      an extra --accent ring (interaction, never a reading).
 * Never a risk colour; the NDCI ramp is the raster's alone. The pins are
 * squares/diamonds, so a station is never confused with a pin.
 *
 * Keyboard: Leaflet markers with `keyboard` are focusable (Tab) and fire
 * `click` on Enter; the left card lists every station as a real button
 * too. Marker clicks do not bubble to the map (`bubblingMouseEvents:
 * false`), so selecting a station never reads the raster cell under it.
 *
 * Limitations: a station without coordinates is listed, not drawn.
 */
import L from 'leaflet'
import { Marker } from 'react-leaflet'
import { useLang } from '../i18n/useLang.js'

const icons = new Map()

/** API text into divIcon HTML: escaped, never interpreted. */
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]))
}

function siteIcon(kind, selected, label) {
  const key = `${kind}|${selected ? 1 : 0}|${label}`
  if (!icons.has(key)) {
    const safeKind = ['reading', 'no_data', 'not_checked'].includes(kind) ? kind : 'no_data'
    icons.set(key, L.divIcon({
      className: 'pw-site-marker-wrap',
      html: `<span class="pw-site-marker" data-kind="${safeKind}"${selected ? ' data-selected="true"' : ''}>`
        + '<span class="pw-site-dot" aria-hidden="true"></span>'
        + `<span class="pw-site-label">${escapeHtml(label)}</span></span>`,
      iconSize: null,
      iconAnchor: [9, 9],
    }))
  }
  return icons.get(key)
}

export default function MapSiteMarkers({ sites, selectedId = null, onSelect }) {
  const { t } = useLang()
  if (!sites || sites.state !== 'ready') return null
  return sites.items.filter((s) => s.onMap).map((s) => {
    const selected = s.id === selectedId
    const label = t('glass.marker.site', { name: s.name, status: t(`status.${s.primaryChip.key}`) })
    return (
      <Marker
        key={s.id}
        position={[s.lat, s.lng]}
        icon={siteIcon(s.kind, selected, label)}
        title={label}
        alt={label}
        keyboard
        bubblingMouseEvents={false}
        zIndexOffset={selected ? 900 : 100}
        eventHandlers={{ click: () => onSelect?.(s.id) }}
      />
    )
  })
}
