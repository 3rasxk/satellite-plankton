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
 * Decorative NDCI-mode texture (docs/superpowers/specs/2026-08-26-hab-
 * sentinel-dashboard-design.md, Screen 1). Domain-warped noise on the
 * diverging ramp — illustrative only, NOT a real per-pixel NDCI raster
 * (no such backend endpoint exists). Regenerated once per mount
 * (useMemo, empty deps) so it doesn't re-warp on every re-render.
 */
export default function NdciRasterOverlay() {
  const dataUrl = useMemo(() => fieldToDataUrl(256, 7), [])
  return <ImageOverlay url={dataUrl} bounds={NDCI_OVERLAY_BOUNDS} opacity={0.65} />
}
