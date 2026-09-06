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
