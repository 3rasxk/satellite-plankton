/**
 * The stations of the glass UI, shared by the map and the summary: GET
 * /risk-map stations, pinned on the measured raster (placement.js), with the
 * alert level of the place each pin is drawn on.
 *
 * Alert level: a station whose pin lands on a cell the API flags (robust z
 * against that cell's own seasonal history, from GET /raster-scan/highlights;
 * `watch` at z >= 2.0, `high` at z >= 3.0) is shown as Watch / Warning and
 * carries that cell's z. Other stations keep their own level. The z
 * boundaries are provisional, not validated bloom thresholds.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { getHighlights, getRasterPixel } from '../api/client.js'
import { useApi } from '../hooks/useApi.js'
import { sortStations, stationsOf } from './model.js'
import { usePlacedStations } from './placement.js'

/** z boundaries of the alert levels (provisional, not validated). */
export const LEVELS = Object.freeze([['warning', 3.0], ['watch', 2.0], ['elevated', 1.5]])
export const levelOfZ = (z) => (Number.isFinite(z) ? (LEVELS.find(([, at]) => z >= at)?.[0] ?? 'normal') : null)

const SAMPLE_STEP = 0.05
const SAMPLE_HALF = 2 // 5 x 5 points, +-0.1 degrees
const POOL = 6
const sampled = new Map() // `${runId}|${id}` -> Promise<{lat,lng,z}|null>

/** The strongest cell of the NDCI map near a station, read cell by cell. */
function sampleStation(runId, s) {
  const key = `${runId}|${s.id}|${s.pinLat.toFixed(4)},${s.pinLng.toFixed(4)}`
  if (!sampled.has(key)) {
    const pts = []
    for (let i = -SAMPLE_HALF; i <= SAMPLE_HALF; i += 1) {
      for (let j = -SAMPLE_HALF; j <= SAMPLE_HALF; j += 1) pts.push([s.pinLat + i * SAMPLE_STEP, s.pinLng + j * SAMPLE_STEP])
    }
    sampled.set(key, (async () => {
      let best = null
      let next = 0
      const worker = async () => {
        while (next < pts.length) {
          const [la, ln] = pts[next]
          next += 1
          try {
            const r = await getRasterPixel(la, ln, runId)
            const z = r?.state === 'reading' ? r?.anomaly?.robust_z : null
            if (Number.isFinite(z) && (best === null || z > best.z)) {
              best = { lat: r.pixel_centre_lat ?? r.cell_lat, lng: r.pixel_centre_lng ?? r.cell_lng, z }
            }
          } catch { /* a point outside the raster has no cell */ }
        }
      }
      await Promise.all(Array.from({ length: POOL }, worker))
      return best
    })())
  }
  return sampled.get(key)
}

const readings = new Map()
/** One cell's reading, cached per run and cell. */
function cellReading(runId, lat, lng) {
  const key = `${runId}|${lat.toFixed(4)},${lng.toFixed(4)}`
  if (!readings.has(key)) {
    readings.set(key, getRasterPixel(lat, lng, runId).then((r) => {
      if (r?.state !== 'reading') return null
      const v = r.index_values ?? {}
      return { ndci: v.ndci ?? null, bda2: v.bda2 ?? null, bda3: v.bda3 ?? null, date: r.acquired_date ?? null, z: Number.isFinite(r.anomaly?.robust_z) ? r.anomaly.robust_z : null }
    }).catch(() => null))
  }
  return readings.get(key)
}

export default function useStations() {
  const { scan, risk } = useOutletContext()
  const data = scan.data
  const raw = useMemo(() => stationsOf(risk.data), [risk.data])
  const runId = Number.isInteger(data?.run_id) ? data.run_id : null
  const fetchCells = useCallback(function fetchCells() {
    // Up to 200 flagged cells (the API allows that after its limit was raised);
    // an older server caps at 10.
    return getHighlights({ n: 200, run_id: runId }).catch(() => getHighlights({ n: 10, run_id: runId }))
  }, [runId])
  const req = useApi(fetchCells, [runId], { enabled: runId !== null })
  const cells = useMemo(() => {
    const pins = Array.isArray(req.data?.pins) ? req.data.pins : []
    return pins
      .filter((p) => (p.anomaly_level === 'high' || p.anomaly_level === 'watch') && p.edge_of_no_data !== true)
      .sort((a, b) => (b.robust_z ?? 0) - (a.robust_z ?? 0))
      .map((p) => ({ lat: p.pixel_centre_lat ?? p.cell_lat, lng: p.pixel_centre_lng ?? p.cell_lng, z: p.robust_z, level: p.anomaly_level }))
      .filter((c) => Number.isFinite(c.lat) && Number.isFinite(c.lng))
  }, [req.data])
  const placed = usePlacedStations(raw, data, cells)

  // Stations with no strongly flagged cell nearby: read the map's own cells
  // around them (GET /raster-scan/pixel) and take the strongest.
  const [near, setNear] = useState({})
  const todo = useMemo(() => (placed ?? []).filter((s) => runId !== null && s.hasReading && !s.rated && !s.flagged && s.pinLat !== null), [placed, runId])
  useEffect(() => {
    let alive = true
    todo.forEach((s) => {
      sampleStation(runId, s).then((best) => { if (alive && best) setNear((p) => (p[`${runId}|${s.id}`] ? p : { ...p, [`${runId}|${s.id}`]: best })) })
    })
    return () => { alive = false }
  }, [todo, runId])

  const positioned = useMemo(() => {
    if (!placed) return null
    return placed.map((s) => {
      if (s.rated || !s.hasReading) return s
      if (s.flagged) {
        return { ...s, cls: levelOfZ(s.flagged.z) ?? 'warning', testClass: true, z: Number.isFinite(s.flagged.z) ? s.flagged.z : s.z }
      }
      const n = near[`${runId}|${s.id}`]
      const lv = n ? levelOfZ(n.z) : null
      if (n && lv && lv !== 'normal') {
        return { ...s, pinLat: n.lat, pinLng: n.lng, moved: true, cls: lv, testClass: true, z: n.z }
      }
      return s
    })
  }, [placed, near, runId])

  // The reading of the cell each pin sits on (GET /raster-scan/pixel): index
  // values, scene date and z come from that cell, so the pin, the NDCI map,
  // the panel and the imagery crop all describe the same place.
  const [cellData, setCellData] = useState({})
  const pinKey = (s) => `${runId}|${s.pinLat?.toFixed(4)},${s.pinLng?.toFixed(4)}`
  useEffect(() => {
    if (!positioned || runId === null) return undefined
    let alive = true
    positioned.forEach((s) => {
      if (s.rated || s.pinLat === null) return
      const k = pinKey(s)
      cellReading(runId, s.pinLat, s.pinLng).then((r) => { if (alive && r) setCellData((p) => (p[k] ? p : { ...p, [k]: r })) })
    })
    return () => { alive = false }
  }, [positioned, runId]) // eslint-disable-line react-hooks/exhaustive-deps

  return useMemo(() => {
    if (!positioned) return null
    return sortStations(positioned.map((s) => {
      const c = s.rated ? null : cellData[pinKey(s)]
      if (!c) return s
      const lv = levelOfZ(c.z)
      return {
        ...s,
        hasReading: true,
        status: 'ok',
        reason: null,
        ndci: c.ndci,
        bda2: c.bda2,
        bda3: c.bda3,
        date: c.date ?? s.date,
        z: c.z ?? s.z,
        cls: lv ?? s.cls,
        testClass: true,
        cell: { lat: s.pinLat, lng: s.pinLng },
      }
    }))
  }, [positioned, cellData]) // eslint-disable-line react-hooks/exhaustive-deps
}
