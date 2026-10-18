/**
 * The raster page's layer selector (True Color / NDCI Raster)
 * and the overlay each layer mounts.
 *
 * 2026-10 glass restyle: drawn as an iOS segmented control (`pw-seg`) in the
 * map's bottom dock; the order is True Color, then NDCI.
 *
 * Text comes from i18n `map.layer.*` through a `t` prop (default Thai): the
 * component deliberately uses no hooks, so it stays callable as a plain
 * function (tests/rasterLayerSwitcher.test.js reads its tree directly). The
 * two layer names are product names and read the same in both languages.
 */
import L from 'leaflet'
import RasterOverlay from './RasterOverlay.jsx'
import { createT } from '../i18n/index.js'

const MODES = ['true_color', 'ndci']

const defaultT = createT('th')

// The switcher may sit inside the Leaflet map, where React's synthetic
// stopPropagation does not reach Leaflet's native listeners: without this a
// click on a button would also pick the map pixel under it and a double
// click would zoom. A callback ref (not a hook) keeps the component callable
// as a plain function; the listeners die with the element. On /map it sits
// in the rail, outside the map, and the shield is a harmless second guard.
const shieldFromMap = (el) => {
  if (!el) return
  L.DomEvent.disableClickPropagation(el)
  L.DomEvent.disableScrollPropagation(el)
}

export default function RasterLayerSwitcher({ mode, onModeChange, trueColorAvailable, t = defaultT }) {
  const unavailable = t('map.layer.true_color_unavailable')
  return (
    <div ref={shieldFromMap} className="leaflet-bar raster-layer-switcher pw-seg" role="group" aria-label={t('map.layer.group')}>
      {MODES.map((value) => {
        const label = t(`map.layer.${value}`)
        const off = value === 'true_color' && !trueColorAvailable
        return (
          <button
            type="button"
            key={value}
            className="pw-seg-btn"
            data-layer-mode={value}
            aria-pressed={mode === value}
            disabled={off}
            title={off ? t('map.layer.true_color_unavailable_title') : undefined}
            aria-label={off ? `${label} — ${unavailable}` : label}
            onMouseDown={(event) => event.stopPropagation()}
            onDoubleClick={(event) => event.stopPropagation()}
            onClick={(event) => {
              event?.stopPropagation?.()
              onModeChange(value)
            }}
          >
            <span>{label}</span>
            {off && <small>{unavailable}</small>}
          </button>
        )
      })}
    </div>
  )
}

export function RasterMapLayers({ mode, data, t = defaultT }) {
  if (mode === 'true_color') {
    return (
      <RasterOverlay
        data={data}
        urlField="true_color_url"
        className="raster-overlay-image raster-true-color-image"
        alt={t('map.layer.true_color_alt')}
        opacity={1}
      />
    )
  }
  if (mode === 'ndci') return <RasterOverlay data={data} alt={t('map.layer.ndci_alt')} />
  return null
}
