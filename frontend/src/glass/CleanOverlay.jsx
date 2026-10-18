/** The NDCI layer on the map (see cleanImage.js for what it shows and how). */
import { useEffect, useState } from 'react'
import { ImageOverlay, Polygon } from 'react-leaflet'
import { apiAssetUrl } from '../api/client.js'
import { MAP_BOUNDS } from '../utils/mapBounds.js'
import { build, cache } from './cleanImage.js'

// Everything outside MAP_BOUNDS (never scanned), in the ramp's mid colour for a
// typical NDCI: a world-sized ring with MAP_BOUNDS cut out.
const OUTSIDE_FILL = '#48C9A9'
const [[S0, W0], [N0, E0]] = MAP_BOUNDS
const OUTSIDE = [
  [[-85, -180], [-85, 180], [85, 180], [85, -180]],
  [[S0, W0], [S0, E0], [N0, E0], [N0, W0]],
]

export default function CleanOverlay({ data, opacity = 0.92, onDetail }) {
  const raw = typeof data?.overlay_url === 'string' ? apiAssetUrl(data.overlay_url) : null
  const hiresRaw = Number.isInteger(data?.run_id) ? apiAssetUrl(`/raster-scan/ndci-hires.png?run_id=${data.run_id}`) : null
  const bounds = data?.bounds
  const [done, setDone] = useState(null) // { raw, href }: the 200 m raster
  const [fine, setFine] = useState(null) // { raw, href }: the ~40 m Sentinel-2 NDCI

  useEffect(() => {
    if (!raw || !bounds) return undefined
    let alive = true
    if (!cache.has(raw)) cache.set(raw, build(raw, bounds))
    cache.get(raw).then((href) => { if (alive) setDone({ raw, href }) }).catch(() => { cache.delete(raw); if (alive) setDone({ raw, href: raw }) })
    return () => { alive = false }
  }, [raw, bounds])

  // The per-pixel Sentinel-2 NDCI replaces the 200 m cells when it is ready
  // (the first render by Earth Engine can take a minute or more).
  useEffect(() => {
    if (!hiresRaw || !bounds) return undefined
    let alive = true
    onDetail?.('loading')
    if (!cache.has(hiresRaw)) cache.set(hiresRaw, build(hiresRaw, MAP_BOUNDS, true))
    cache.get(hiresRaw)
      .then((href) => { if (alive) { setFine({ raw: hiresRaw, href }); onDetail?.('ready') } })
      .catch(() => { cache.delete(hiresRaw); if (alive) onDetail?.('unavailable') })
    return () => { alive = false }
  }, [hiresRaw, bounds]) // eslint-disable-line react-hooks/exhaustive-deps

  const use = fine?.raw === hiresRaw ? fine : done?.raw === raw ? done : null
  if (!bounds || !use) return <Polygon positions={OUTSIDE} interactive={false} pathOptions={{ stroke: false, fillColor: OUTSIDE_FILL, fillOpacity: 1 }} />
  const mask = <Polygon positions={OUTSIDE} interactive={false} pathOptions={{ stroke: false, fillColor: OUTSIDE_FILL, fillOpacity: 1 }} />
  return <><ImageOverlay url={use.href} bounds={use.href === raw ? bounds : MAP_BOUNDS} opacity={opacity} className="raster-overlay-image" alt="NDCI over the sea of the study area" />{mask}</>
}
