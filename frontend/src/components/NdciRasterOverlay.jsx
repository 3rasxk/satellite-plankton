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
 * Composite Index Map overlay: NDCI + 2BDA + 3BDA, water-masked.
 *
 * This is still an illustrative texture (no backend raster endpoint
 * exists), but it now:
 *  1. Applies a water mask so only sea pixels are coloured — land is
 *     transparent.
 *  2. Labels the overlay as a multi-index composite (NDCI + 2BDA + 3BDA)
 *     rather than NDCI-only.
 *
 * The water mask is a simplified polygon approximation of the upper Gulf
 * of Thailand coastline, rasterised at overlay resolution.
 */
export default function NdciRasterOverlay() {
  const dataUrl = useMemo(() => fieldToDataUrl(512, 7, { waterMask: true }), [])
  return <ImageOverlay url={dataUrl} bounds={NDCI_OVERLAY_BOUNDS} opacity={0.85} />
}
