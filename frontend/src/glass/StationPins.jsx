/**
 * The monitoring stations on the map, drawn as the design's pins: a 16px
 * dot (20px for Warning) with a 2.5px white ring and shadow, a glass
 * "Name · Class" chip, a halo for Warning and a blue ring when selected.
 * No data / not checked: hollow white pin with a 2px #AEAEB2 ring.
 * The chip's side (right / left / below) is decided by MapViewport so no
 * label sits under a panel or over another pin.
 *
 * Data source: `stations` from ./model.js over GET /risk-map.
 */
import L from 'leaflet'
import { Marker } from 'react-leaflet'
import { LV } from './model.js'

const cache = new Map()
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

function pinIcon(s, selected) {
  const key = `${s.cls}|${selected ? 1 : 0}|${s.short}`
  if (!cache.has(key)) {
    const lv = LV[s.cls]
    const r = s.cls === 'warning' ? 10 : 8
    const dot = lv.hollow ? '' : `background:${lv.color};`
    cache.set(key, L.divIcon({
      className: 'gl-pin-wrap',
      iconSize: [0, 0],
      iconAnchor: [0, 0],
      html: `<span class="gl-pin" style="--r:${r}px" data-class="${s.cls}" data-hollow="${lv.hollow ? 'true' : 'false'}" data-side="right"${selected ? ' data-selected="true"' : ''}>`
        + `<span class="gl-pin-dot" style="${dot}"></span>`
        + `<span class="gl-pin-chip">${esc(s.short)}<span> · ${esc(lv.label)}</span></span></span>`,
    }))
  }
  return cache.get(key)
}

export default function StationPins({ stations, selectedId, onSelect }) {
  if (!stations) return null
  const placed = stations.filter((s) => s.lat !== null && s.lng !== null)
  const pins = placed.map((s) => {
    const selected = s.id === selectedId
    return (
      <Marker
        key={s.id}
        position={[s.pinLat ?? s.lat, s.pinLng ?? s.lng]}
        icon={pinIcon(s, selected)}
        title={`${s.short}: ${LV[s.cls].label}`}
        alt={`${s.short}: ${LV[s.cls].label}`}
        keyboard
        bubblingMouseEvents={false}
        zIndexOffset={selected ? 900 : s.cls === 'warning' ? 400 : 100}
        eventHandlers={{ click: () => onSelect?.(s.id) }}
      />
    )
  })
  return pins
}
