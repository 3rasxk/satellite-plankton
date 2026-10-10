// React rendering boundary for Leaflet; no browser or tile requests in tests.
import { createElement } from 'react'

export const CircleMarker = ({ center, children }) => createElement(
  'div', { 'data-scan-marker': `${center[0]},${center[1]}` }, children,
)
export const MapContainer = ({ children, className }) => createElement('main', { className }, children)
// A pin marker: records its position and rank (from the divIcon html) so a
// test can see which pins were drawn without a DOM.
export const Marker = ({ position, icon, title }) => createElement('div', {
  'data-pin-marker': `${position[0]},${position[1]}`,
  'data-pin-title': title,
  'data-pin-icon': icon?.options?.html ?? '',
})
export const Tooltip = ({ children }) => createElement('div', null, children)
export const Popup = ({ children }) => createElement('section', null, children)
export const TileLayer = ({ url, attribution, pane }) => createElement('span', {
  'data-tile-url': url,
  'data-tile-attribution': attribution,
  'data-tile-pane': pane,
})
export const Pane = ({ children, name }) => createElement('div', { 'data-pane-name': name }, children)
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
