import { Fragment, useMemo } from 'react'
import { CircleMarker, Tooltip } from 'react-leaflet'
import {
  RISK_COLOR_HEX,
  NO_DATA_HEX,
  NO_DATA_LINE_HEX,
  REGIONAL_PRIMARY_INDEX,
  REGIONAL_INDEX_LABEL,
  regionalIndexDomain,
  regionalIndexColor,
  formatIndexValue,
} from '../constants.js'

/**
 * Full-polygon regional bloom scan overlay (backend GET /regional-scan) --
 * a distinct layer from RiskMap.jsx's 6-site monitoring grid, per spec
 * §0/§10: does not touch or replace that grid or any of its markers.
 * Renders real NDCI/2BDA/3BDA values in each pin's popup -- never a
 * colored dot with no data behind it (no-fabrication rule, §0).
 * Must be rendered inside a react-leaflet <MapContainer>.
 *
 * Interim render (index values only). The previous version gated every
 * pin on `point.threshold_tier` and coloured it from RISK_COLOR_HEX.
 * `threshold_tier` is null on all 501 points of the latest run -- the
 * anomaly cutoffs in detection/src/config.yaml are UNCALIBRATED and no
 * point cleared them -- so that gate drew nothing at all. Gating on a
 * real primary-index value instead makes the scan's actual output
 * visible, and the neutral --regional-index-* ramp keeps it honest: the
 * shade means "this pixel's NDCI reading, relative to the rest of this
 * scan", not a risk tier. See RegionalScanBanner.jsx for the matching
 * on-map wording and legend.
 *
 * Status handling, per status field (never merged into one colour):
 *   ok / no_climatology -> real index_values, drawn on the neutral ramp
 *   no_imagery          -> small hollow grey marker (nothing was seen)
 *   no_water_pixels     -> not drawn (177 of 501 on the latest run;
 *                          drawing them would bury the readings under
 *                          land/cloud-masked cells)
 *   error               -> not drawn (no index_values to show)
 */
export default function RegionalScanLayer({ data }) {
  const clusters = data?.clusters || []
  const points = data?.points || []

  // Points already covered by a cluster are shown once, via the
  // cluster marker -- avoids stacking a cluster circle directly on top
  // of its own single-point members.
  const clusteredPointIds = useMemo(
    () => new Set(clusters.flatMap((c) => c.member_point_ids)),
    [clusters],
  )
  const indexPoints = useMemo(
    () =>
      points.filter(
        (p) =>
          typeof p.index_values?.[REGIONAL_PRIMARY_INDEX] === 'number' &&
          !clusteredPointIds.has(p.point_id),
      ),
    [points, clusteredPointIds],
  )
  const noImageryPoints = useMemo(
    () => points.filter((p) => p.status === 'no_imagery'),
    [points],
  )
  const domain = useMemo(() => regionalIndexDomain(indexPoints), [indexPoints])

  if (!data?.run) return null

  const run = data.run
  // Run-level fallback only, for points with no scene date of their own.
  // Neither run-level date is any particular pin's scene: date_used is the
  // target date handed to detect(), and newest_scene_date is a poll-level
  // measurement -- both are the same string for all 501 pins. So label this
  // as the scan target date and never as a scene date.
  const runFallbackLine = run.date_used ? `scan target date ${run.date_used}` : null

  // This pin's own Sentinel-2 scene. get_sentinel2_bands resolves the
  // nearest cloud-free scene within ±10 days, so a single scan is routinely
  // backed by scenes several days apart from each other -- show each pin's
  // real vintage and its offset instead of implying one scan-wide date.
  const sceneLineFor = (point) => {
    const actual = point.actual_date
    if (!actual) return runFallbackLine
    const scene = actual.slice(0, 10)
    if (!run.date_used || scene === run.date_used) return `scene ${scene}`
    const offsetDays = Math.round(
      (Date.parse(`${run.date_used}T00:00:00Z`) - Date.parse(`${scene}T00:00:00Z`)) / 86400000,
    )
    // Unparseable date: show the scene, never a made-up offset.
    if (!Number.isFinite(offsetDays) || offsetDays === 0) return `scene ${scene}`
    const magnitude = Math.abs(offsetDays)
    const unit = magnitude === 1 ? 'day' : 'days'
    // The search window is ±10 days, so a scene can also post-date the scan.
    return offsetDays > 0
      ? `scene ${scene} · ${magnitude} ${unit} before scan date`
      : `scene ${scene} · ${magnitude} ${unit} after scan date`
  }

  return (
    <>
      {clusters.map((cluster, i) => (
        <CircleMarker
          key={`cluster-${i}`}
          center={[cluster.centroid_lat, cluster.centroid_lng]}
          radius={Math.min(10 + cluster.cell_count * 2, 40)}
          pathOptions={{
            color: RISK_COLOR_HEX[cluster.threshold_tier],
            weight: 1.5,
            fillColor: RISK_COLOR_HEX[cluster.threshold_tier],
            fillOpacity: 0.35,
          }}
        >
          <Tooltip direction="top" offset={[0, -10]} opacity={0.95}>
            <div style={{ fontWeight: 600, fontSize: '13px' }}>
              Cluster of {cluster.cell_count} cells
            </div>
            <div style={{ fontSize: '11.5px', marginTop: '2px', color: '#1d1d1f' }}>
              mean anomaly_z {cluster.mean_anomaly_z.toFixed(2)} · max {cluster.max_anomaly_z.toFixed(2)}
            </div>
          </Tooltip>
        </CircleMarker>
      ))}
      {noImageryPoints.map((point) => (
        <CircleMarker
          key={`no-imagery-${point.point_id}`}
          center={[point.lat, point.lng]}
          radius={3}
          pathOptions={{
            color: NO_DATA_LINE_HEX,
            weight: 1,
            // Visually hollow, but still a filled path: SVG hit-testing
            // under pointer-events: visiblePainted ignores the interior of
            // a fill="none" shape, which would leave this 3px marker
            // hoverable only exactly on its 1px ring. fillOpacity 0 keeps
            // it transparent while keeping the disc hoverable.
            fillColor: NO_DATA_HEX,
            fillOpacity: 0,
          }}
        >
          <Tooltip direction="top" offset={[0, -5]} opacity={0.95}>
            <div style={{ fontSize: '11.5px' }}>No satellite pass — nothing measured here</div>
          </Tooltip>
        </CircleMarker>
      ))}
      {indexPoints.map((point) => {
        const primary = point.index_values[REGIONAL_PRIMARY_INDEX]
        const others = Object.entries(point.index_values).filter(
          ([key, value]) => key !== REGIONAL_PRIMARY_INDEX && typeof value === 'number',
        )
        const sceneLine = sceneLineFor(point)
        return (
          <Fragment key={point.point_id}>
            <CircleMarker
              center={[point.lat, point.lng]}
              radius={6}
              pathOptions={{
                color: '#ffffff',
                weight: 1,
                fillColor: regionalIndexColor(primary, domain),
                fillOpacity: 0.85,
              }}
            >
              <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
                <div style={{ fontWeight: 600, fontSize: '12.5px' }}>
                  {REGIONAL_INDEX_LABEL[REGIONAL_PRIMARY_INDEX]} {formatIndexValue(primary)}
                </div>
                {others.length > 0 && (
                  <div style={{ fontSize: '11.5px', marginTop: '2px' }}>
                    {others
                      .map(([key, value]) => `${REGIONAL_INDEX_LABEL[key] || key} ${formatIndexValue(value)}`)
                      .join(' · ')}
                  </div>
                )}
                {sceneLine && (
                  <div style={{ fontSize: '11px', marginTop: '2px', color: '#6e6e73' }}>{sceneLine}</div>
                )}
                <div style={{ fontSize: '11px', marginTop: '2px', color: '#6e6e73' }}>
                  {point.anomaly_z === null || point.anomaly_z === undefined
                    ? 'no anomaly score — spatial trigger not yet active'
                    : 'anomaly score not shown — spatial trigger not yet active'}
                </div>
              </Tooltip>
            </CircleMarker>
          </Fragment>
        )
      })}
    </>
  )
}
