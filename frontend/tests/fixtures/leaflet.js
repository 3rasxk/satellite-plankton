// React rendering boundary for Leaflet; no browser or tile requests in tests.
import { createElement } from 'react'

export const CircleMarker = ({ center, children }) => createElement(
  'div', { 'data-scan-marker': `${center[0]},${center[1]}` }, children,
)
export const MapContainer = ({ children }) => createElement('main', null, children)
export const Tooltip = ({ children }) => createElement('div', null, children)
export const Popup = ({ children }) => createElement('section', null, children)
export const TileLayer = () => null
export const ZoomControl = () => null
export const useMap = () => ({ fitBounds() {}, setView() {} })

// Map event handlers, recorded so a test can fire one. Parked on
// globalThis rather than exported state because the component under test
// imports this module through Vite's SSR graph while the test file loads
// it as an ordinary Node module -- two module instances, one process, so
// a shared global is the only handle both of them actually see.
export const useMapEvents = (handlers) => {
  globalThis.__leafletMapHandlers = handlers
  return { fitBounds() {}, setView() {} }
}
export const ImageOverlay = ({ url, bounds, opacity, className }) => createElement(
  'img', {
    'data-overlay-url': url,
    'data-overlay-bounds': JSON.stringify(bounds),
    'data-overlay-opacity': String(opacity),
    className,
  },
)
