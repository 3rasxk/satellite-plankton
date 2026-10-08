import { useMemo } from 'react'
import { ImageOverlay } from 'react-leaflet'
import { fieldToDataUrl } from '../utils/noiseField.js'

// Fixed bounds roughly covering the monitored grid's extent with margin —
// see backend/src/grid.py: sites span ~12.75-13.5N, 100.05-100.99E.
const NDCI_OVERLAY_BOUNDS = [
  [12.55, 99.85],
  [13.75, 101.15],
]

/**
 * Deprecated illustrative texture retained for historical source context.
 * No route imports this component. The raster page uses RasterOverlay with
 * run-owned backend PNGs; this synthetic texture must never be presented as
 * satellite data, NDCI, anomaly, or bloom risk.
 */
export default function NdciRasterOverlay() {
  const dataUrl = useMemo(() => fieldToDataUrl(512, 7, { waterMask: true }), [])
  return <ImageOverlay url={dataUrl} bounds={NDCI_OVERLAY_BOUNDS} opacity={0.85} />
}
