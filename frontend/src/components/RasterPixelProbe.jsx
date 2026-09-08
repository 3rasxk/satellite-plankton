/**
 * Turns a click on the raster map into a coordinate to ask the API about.
 *
 * Renders nothing. It exists as its own component because `useMapEvents`
 * only works inside the `MapContainer` tree, and the panel that shows the
 * answer belongs outside it (over the map, not on it).
 *
 * The coordinate is passed through exactly as Leaflet reports it, in
 * (lat, lng) order. That ordering is the one thing here that can break
 * silently: swapped, a click in the upper Gulf becomes a query somewhere
 * off Somalia, the API answers "outside the study area" quite correctly,
 * and the map looks fine. The suite asserts the order for that reason.
 */
import { useMapEvents } from 'react-leaflet'

export default function RasterPixelProbe({ onPick }) {
  useMapEvents({
    click(event) {
      if (!onPick) return
      const { lat, lng } = event.latlng
      onPick({ lat, lng })
    },
  })
  return null
}
