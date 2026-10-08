/**
 * The raster overlay itself: a cached PNG placed on the map by its
 * stated bounds.
 *
 * `ImageOverlay`, not the GEE XYZ tile template -- that URL carries an
 * expiring token and would put a live Earth Engine dependency in every
 * viewer's browser. The image served here was rendered once, from the
 * cells that were actually stored.
 *
 * `image-rendering: pixelated` (applied via .raster-overlay-image in
 * global.css) is load-bearing, not cosmetic. Smooth scaling blends
 * neighbouring measurements into colours that are not on the stored
 * pixel grid and can bleed colour into transparent no-data edges.
 *
 * Nothing here renders when there is no overlay. An empty layer drawn
 * over the study area would assert "we looked and saw nothing", which
 * is not the same as "we have not looked".
 */
import { ImageOverlay } from 'react-leaflet'
import { apiAssetUrl } from '../api/client.js'

export default function RasterOverlay({
  data,
  opacity = 0.85,
  urlField = 'overlay_url',
  className = 'raster-overlay-image',
  alt = 'ภาพแรสเตอร์ค่าดัชนี NDCI ทั่วพื้นที่ศึกษา',
}) {
  const bounds = data?.bounds
  // Through the API base, not bare: see apiAssetUrl. A bare path resolves
  // against the dev server and renders nothing, silently.
  const url = apiAssetUrl(data?.[urlField])
  if (!bounds || !url) return null

  return (
    <ImageOverlay
      url={url}
      bounds={bounds}
      opacity={opacity}
      className={className}
      alt={alt}
    />
  )
}
