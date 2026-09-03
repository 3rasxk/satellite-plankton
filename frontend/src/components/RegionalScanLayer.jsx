import { Fragment, useMemo } from 'react'
import { CircleMarker, Tooltip } from 'react-leaflet'
import { RISK_COLOR_HEX } from '../constants.js'

/**
 * Full-polygon regional bloom scan overlay (backend GET /regional-scan) --
 * a distinct layer from RiskMap.jsx's 6-site monitoring grid, per spec
 * §0/§10: does not touch or replace that grid or any of its markers.
 * Renders real NDCI/2BDA/3BDA/anomaly_z values in each pin's popup --
 * never a colored dot with no data behind it (no-fabrication rule, §0).
 * Must be rendered inside a react-leaflet <MapContainer>.
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
  const unclustered = useMemo(
    () => points.filter((p) => p.threshold_tier && !clusteredPointIds.has(p.point_id)),
    [points, clusteredPointIds],
  )

  if (!data?.run) return null

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
      {unclustered.map((point) => (
        <Fragment key={point.point_id}>
          <CircleMarker
            center={[point.lat, point.lng]}
            radius={6}
            pathOptions={{
              color: RISK_COLOR_HEX[point.threshold_tier],
              weight: 1.5,
              fillColor: RISK_COLOR_HEX[point.threshold_tier],
              fillOpacity: 0.6,
            }}
          >
            <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
              <div style={{ fontSize: '11.5px' }}>
                anomaly_z {point.anomaly_z?.toFixed(2)}
                {point.index_values
                  ? ` · ${Object.entries(point.index_values)
                      .map(([k, v]) => `${k}=${v.toFixed(3)}`)
                      .join(', ')}`
                  : ''}
              </div>
            </Tooltip>
          </CircleMarker>
        </Fragment>
      ))}
    </>
  )
}
