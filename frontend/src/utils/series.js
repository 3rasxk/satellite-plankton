import { formatZ } from '../constants.js'

/** Build day-segments from a /timeseries `points` array (last N days). */
export function segmentsFromTimeseries(points, days = 90) {
  const slice = (points || []).slice(-days)
  return slice.map((p) => ({
    key: p.date,
    z: p.anomaly_z,
    tooltip:
      p.anomaly_z === null || p.anomaly_z === undefined
        ? `${p.date}: ${p.reason || 'no anomaly value'}`
        : `${p.date}: z=${formatZ(p.anomaly_z)}`,
  }))
}

/** Merge each site's (already-sliced) /timeseries points into one
 * date-keyed table for a multi-line recharts series. Dates that don't
 * exist for a given site are left undefined for that key — recharts
 * draws a real gap rather than interpolating a value that wasn't
 * observed. */
export function mergeSiteSeries(sitesWithPoints) {
  const byDate = new Map()
  for (const { site, points } of sitesWithPoints) {
    for (const p of points) {
      if (!byDate.has(p.date)) byDate.set(p.date, { date: p.date })
      byDate.get(p.date)[site.site_id] = p.chlor_a
    }
  }
  return Array.from(byDate.values()).sort((a, b) => (a.date < b.date ? -1 : 1))
}
