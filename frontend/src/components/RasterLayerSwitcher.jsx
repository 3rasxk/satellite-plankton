import L from 'leaflet'
import RasterOverlay from './RasterOverlay.jsx'

const MODES = [
  ['true_color', 'True Color'],
  ['light_map', 'Light Map'],
  ['ndci', 'NDCI Raster'],
]

// The switcher is a plain DOM child of the Leaflet map, so React's synthetic
// stopPropagation does not reach Leaflet's native listeners: without this a
// click on a button would also pick the map pixel under it and a double
// click would zoom. A callback ref (not a hook) keeps the component callable
// as a plain function; the listeners die with the element.
const shieldFromMap = (el) => {
  if (!el) return
  L.DomEvent.disableClickPropagation(el)
  L.DomEvent.disableScrollPropagation(el)
}

export default function RasterLayerSwitcher({ mode, onModeChange, trueColorAvailable }) {
  return (
    <div ref={shieldFromMap} className="leaflet-bar raster-layer-switcher" role="group" aria-label="เลือกชั้นข้อมูลแผนที่">
      {MODES.map(([value, label]) => (
        <button
          type="button"
          key={value}
          data-layer-mode={value}
          aria-pressed={mode === value}
          disabled={value === 'true_color' && !trueColorAvailable}
          title={value === 'true_color' && !trueColorAvailable
            ? 'ข้อมูลชุดนี้ไม่มีภาพสีธรรมชาติที่ตรงกับรอบสแกน จึงไม่สามารถเปิด True Color ได้'
            : undefined}
          aria-label={value === 'true_color' && !trueColorAvailable
            ? 'True Color — ไม่มีภาพสีธรรมชาติที่ตรงกับรอบสแกน'
            : label}
          onMouseDown={(event) => event.stopPropagation()}
          onDoubleClick={(event) => event.stopPropagation()}
          onClick={(event) => {
            event?.stopPropagation?.()
            onModeChange(value)
          }}
        >
          <span>{label}</span>
          {value === 'true_color' && !trueColorAvailable && (
            <small>ไม่มีภาพสีธรรมชาติที่ตรงกับรอบสแกน</small>
          )}
        </button>
      ))}
    </div>
  )
}

export function RasterMapLayers({ mode, data }) {
  if (mode === 'true_color') {
    return (
      <RasterOverlay
        data={data}
        urlField="true_color_url"
        className="raster-overlay-image raster-true-color-image"
        alt="ภาพสีธรรมชาติ Sentinel-2 จากรอบสแกนที่แสดงอยู่"
        opacity={1}
      />
    )
  }
  if (mode === 'ndci') return <RasterOverlay data={data} />
  return null
}
