/**
 * The raster map's view model (src/lib/mapModel.js), as claims:
 *   - a pin's popup/inspector restates every field the API sent, with its
 *     source, in both pin modes; an unknown is "—" with a reason, never 0;
 *     anomaly values are always TEST; no risk tier is read;
 *   - the counts block lists the API's buckets in a fixed order with
 *     plain-language keys, and the partition check is the API's own sum,
 *     shown (never corrected) when it does not add up;
 *   - a failed pins request is an error with status and reason, never
 *     "no pins";
 *   - the legend text is chosen by mode, and reads exactly as specified;
 *   - the permalink selects the cell or pin it names, flies there, and says
 *     so when its run is no longer served;
 *   - every message key the model produces exists in TH and EN.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import en from '../src/i18n/en.js'
import th from '../src/i18n/th.js'
import { createT } from '../src/i18n/index.js'
import { decodeView } from '../src/lib/permalink.js'
import { renderMessage } from '../src/lib/overviewModel.js'
import {
  applyPermalink, buildCellModel, buildCountsBlock, buildPinView, buildPinsModel, buildRailModel,
  clampPinCount, COUNT_REASON_KEYS, errorInfo, pinLegendKey, pinShape, readPermalink, serializeView,
} from '../src/lib/mapModel.js'
import { HIGHLIGHTS_ANOMALY, HIGHLIGHTS_NDCI, PIXEL_TEST, RASTER } from './fixtures/map_payloads.js'

const NOW = Date.parse('2026-10-10T14:00:00Z')
const lookup = (dict, key) => key.split('.').reduce((node, part) => (node && typeof node === 'object' ? node[part] : undefined), dict)

/** Every i18n key the model names: `{key}` messages and `*Key` fields. */
function keysIn(value, out = new Set()) {
  if (Array.isArray(value)) value.forEach((v) => keysIn(v, out))
  else if (value && typeof value === 'object') {
    for (const [name, v] of Object.entries(value)) {
      if ((name === 'key' || /Key$/.test(name)) && typeof v === 'string' && /^(map|overview)\./.test(v)) out.add(v)
      else keysIn(v, out)
    }
  }
  return out
}

function assertKeysExist(model, label) {
  for (const key of keysIn(model)) {
    assert.equal(typeof lookup(en, key), 'string', `${label}: en.js lacks ${key}`)
    assert.equal(typeof lookup(th, key), 'string', `${label}: th.js lacks ${key}`)
  }
}

const ready = (highlights, extra = {}) => buildPinsModel({ highlights, request: {}, runId: highlights.run_id, n: 5, ...extra })

// ------------------------------------------------------------------ pins

test('anomaly pin view: every field the API sent, with sources, labelled TEST', () => {
  const view = buildPinView(HIGHLIGHTS_ANOMALY, 1)
  const pin = HIGHLIGHTS_ANOMALY.pins[0]
  assert.equal(view.rank, 1)
  assert.equal(view.count, 3)
  assert.equal(view.mode, 'anomaly')
  assert.equal(view.isTest, true)
  assert.equal(view.shape, 'diamond')
  assert.equal(view.legendKey, 'map.pins.legend_anomaly')
  assert.deepEqual(view.indices.map((r) => [r.label, r.href]), [
    ['NDCI', '/methods#ndci'], ['2BDA', '/methods#2bda'], ['3BDA', '/methods#3bda'], ['B2/B3', '/methods#b2_b3_ratio'],
  ])
  assert.equal(view.indices[0].value.text, pin.index_values.ndci.toFixed(4))
  assert.equal(view.indices[0].source.field, 'pins[rank=1].index_values.ndci')
  assert.match(view.indices[0].source.url, /raster-scan\/highlights\?run_id=6&n=5&min_separation_m=3000&mode=anomaly$/)
  // The anomaly rows are the API's numbers, not recomputed.
  const rows = Object.fromEntries(view.anomaly.rows.map((r) => [r.id, r.value]))
  assert.equal(rows.robust_z.raw, pin.robust_z)
  assert.equal(rows.robust_z.text, '14.34')
  assert.equal(rows.median_ndci.raw, pin.median_ndci)
  assert.equal(rows.mad.raw, pin.mad)
  assert.equal(rows.n_dates.text, '50')
  assert.equal(view.anomaly.chip.key, 'anomaly_high_test')
  assert.equal(view.anomaly.baselineVersion, 'TEST-20261009-9fc9a022')
  assert.equal(view.anomaly.seasonKey, 'm10+-1')
  assert.equal(view.percentile.note.key, 'map.pin.percentile_anomaly')
  assert.equal(view.percentile.note.params.assessable, '208,194')
  assert.equal(view.acquiredDate.value.text, '2026-10-07')
  assert.equal(view.acquiredAt.value.text, '2026-10-07 03:54Z')
  assert.equal(view.cell.lat.raw, pin.cell_lat)
  assert.equal(view.centre.lat.raw, pin.pixel_centre_lat)
  assert.notEqual(view.cell.lat.text, view.centre.lat.text, 'observation and drawn square are kept apart')
  assert.equal(view.edge.key, 'map.pin.edge_false')
  assert.deepEqual(view.bands.map((b) => [b.id, b.value.text]), [['red', '141'], ['green', '197'], ['blue', '179']])
  assert.equal(view.caveatKey, 'map.pin.caveat')
  assert.equal(view.disclaimer, HIGHLIGHTS_ANOMALY.disclaimer)
  assert.equal(view.ranking, HIGHLIGHTS_ANOMALY.ranking)
  assert.equal(view.counts.mode, 'anomaly')
  assert.deepEqual(view.target, { lat: pin.pixel_centre_lat, lng: pin.pixel_centre_lng })
  assert.deepEqual(view.cellQuery, { lat: pin.cell_lat, lng: pin.cell_lng })
  const csv = view.csv.content()
  assert.equal(csv.trim().split('\r\n').length, 2, 'the CSV row is this one pin')
  assert.match(csv, /,14\.338169744761082,/)
  assertKeysExist(view, 'anomaly pin view')
})

test('ndci pin view: a ranking, no TEST block; unknowns are "—" with a reason', () => {
  const pins = [{ ...HIGHLIGHTS_NDCI.pins[0], index_values: { ...HIGHLIGHTS_NDCI.pins[0].index_values, bda2: null } }, ...HIGHLIGHTS_NDCI.pins.slice(1)]
  const view = buildPinView({ ...HIGHLIGHTS_NDCI, pins }, 1)
  assert.equal(view.mode, 'ndci')
  assert.equal(view.isTest, false)
  assert.equal(view.shape, 'square')
  assert.equal(view.legendKey, 'map.pins.legend_ndci')
  assert.equal(view.anomaly, null, 'no anomaly rows for a ranking by value')
  const bda2 = view.indices.find((r) => r.id === 'bda2')
  assert.equal(bda2.value.isNull, true)
  assert.equal(bda2.value.text, '—')
  assert.equal(bda2.value.reason, 'unreadable_band')
  assert.equal(view.bands, null, 'this run stored no visible bands')
  assert.equal(view.edge.key, 'map.pin.edge_true')
  assert.equal(view.edge.tone, 'attention')
  assert.equal(view.percentile.note.key, 'map.pin.percentile_ndci')
  assert.equal(view.percentile.note.params.cohort, '83,857')
  assert.equal(view.counts.mode, 'ndci')
  const lowSignal = view.counts.quality.find((r) => r.id === 'excluded_low_signal')
  assert.equal(lowSignal.value.isNull, true, 'a screen that did not run is null, never 0')
  assert.equal(lowSignal.nullKey, 'map.counts.excluded_low_signal_null')
  assert.equal(view.counts.qualityNote, HIGHLIGHTS_NDCI.quality_note)
  assert.equal(JSON.stringify(view).includes('risk_tier'), false)
  assertKeysExist(view, 'ndci pin view')
})

test('a pin view of a rank the response does not hold is null', () => {
  assert.equal(buildPinView(HIGHLIGHTS_ANOMALY, 9), null)
  assert.equal(buildPinView(null, 1), null)
})

test('counts block: the API buckets in fixed order, plain-language keys, partition adds up', () => {
  const counts = buildCountsBlock(HIGHLIGHTS_ANOMALY)
  assert.deepEqual(counts.rows.map((r) => r.id), [
    'measured', 'assessable', ...COUNT_REASON_KEYS, 'watch', 'high', 'flagged_share',
  ])
  assert.deepEqual(COUNT_REASON_KEYS, ['invalid', 'low_signal', 'too_old', 'not_after_history', 'no_baseline', 'insufficient_dates', 'zero_mad'])
  for (const row of counts.rows) {
    assert.equal(row.value.raw, HIGHLIGHTS_ANOMALY.counts[row.id], `${row.id} is the API's count`)
    assert.equal(row.labelKey, `map.counts.${row.id}`)
    assert.equal(row.source.field, `counts.${row.id}`)
  }
  // Zero buckets stay zeros, not dashes.
  assert.equal(counts.rows.find((r) => r.id === 'zero_mad').value.text, '0')
  assert.equal(counts.rows.find((r) => r.id === 'flagged_share').value.text, '11.08 %')
  assert.equal(counts.partition.ok, true)
  assert.equal(counts.partition.sum, 209594)
  assert.equal(counts.partition.message.key, 'map.counts.partition_ok')
  assert.deepEqual(counts.quality.map((r) => [r.id, r.value.text]), [['excluded_degenerate', '90'], ['excluded_low_signal', '671']])
  const t = createT('en')
  assert.equal(renderMessage(t, counts.partition.message), 'Assessable plus not-assessable cells: 209,594 = 209,594 measured cells (the counts add up).')
  assertKeysExist(counts, 'counts')
})

test('counts block: a partition that does not add up is shown as received, never corrected', () => {
  const off = { ...HIGHLIGHTS_ANOMALY, counts: { ...HIGHLIGHTS_ANOMALY.counts, too_old: 6 } }
  const counts = buildCountsBlock(off)
  assert.equal(counts.partition.ok, false)
  assert.equal(counts.partition.message.key, 'map.counts.partition_mismatch')
  assert.equal(counts.partition.message.tone, 'attention')
  assert.equal(counts.partition.message.params.diff, '6')
  assert.equal(counts.rows.find((r) => r.id === 'measured').value.raw, 209594, 'measured is not rewritten')
  const missing = buildCountsBlock({ ...HIGHLIGHTS_ANOMALY, counts: { ...HIGHLIGHTS_ANOMALY.counts, zero_mad: null, flagged_share: null } })
  assert.equal(missing.partition.ok, null)
  assert.equal(missing.partition.message.key, 'map.counts.partition_unknown')
  const share = missing.rows.find((r) => r.id === 'flagged_share')
  assert.equal(share.value.isNull, true)
  assert.equal(share.nullKey, 'map.counts.flagged_share_null')
})

test('pins model: every state is distinct; an error is never "no pins"', () => {
  assert.equal(buildPinsModel({ runId: null }).state, 'no_raster')
  assert.equal(buildPinsModel({ runId: 6, request: { loading: true } }).state, 'loading')
  assert.equal(buildPinsModel({ runId: 6, highlights: null }).state, 'loading')

  const conflict = { response: { status: 409, data: { detail: { reason: 'mode_off', cause: null, season_key: null, message: 'anomaly mode needs BASELINE_MODE=test' } } } }
  const failed = buildPinsModel({ runId: 6, n: 7, request: { error: conflict } })
  assert.equal(failed.state, 'error')
  assert.deepEqual(failed.error, {
    status: 409, reason: 'mode_off', message: 'anomaly mode needs BASELINE_MODE=test', noResponse: false,
    endpoint: '/raster-scan/highlights?n=7&run_id=6',
  })
  assert.equal(failed.items.length, 0)
  assert.ok(!failed.notes.some((n) => n.key === 'map.pins.none'), 'an error is not an empty result')
  const gone = errorInfo({ response: { status: 404, data: { detail: 'No raster overlay is available to query.' } } })
  assert.deepEqual([gone.status, gone.reason, gone.message], [404, null, 'No raster overlay is available to query.'])
  assert.equal(errorInfo(new Error('Network Error')).noResponse, true)

  assert.equal(buildPinsModel({ runId: 7, highlights: HIGHLIGHTS_ANOMALY }).state, 'other_run')
  assert.equal(buildPinsModel({ runId: 6, highlights: { ...HIGHLIGHTS_ANOMALY, mode: 'tier' } }).state, 'unknown_mode')

  const empty = ready({ ...HIGHLIGHTS_ANOMALY, pins: [], reason: 'no cells meet the condition (0 assessable of 10 measured)' })
  assert.equal(empty.state, 'empty')
  assert.equal(empty.serverReason, 'no cells meet the condition (0 assessable of 10 measured)')
  assert.ok(empty.counts, 'an empty anomaly result still says how many cells were assessable')
})

test('pins model: rank order, TEST chips in anomaly mode only, fewer and hidden notes', () => {
  const reversed = { ...HIGHLIGHTS_ANOMALY, pins: [...HIGHLIGHTS_ANOMALY.pins].reverse() }
  const model = ready(reversed)
  assert.equal(model.state, 'ready')
  assert.deepEqual(model.items.map((p) => p.rank), [1, 2, 3])
  assert.equal(model.shape, 'diamond')
  assert.equal(model.legendKey, 'map.pins.legend_anomaly')
  assert.equal(model.items[0].chip.key, 'anomaly_high_test')
  assert.equal(model.items[0].z.text, '14.34')
  assert.equal(model.items[0].lat, HIGHLIGHTS_ANOMALY.pins[0].pixel_centre_lat)
  assert.deepEqual(model.notes.map((n) => n.key), ['map.pins.fewer'])
  const hidden = ready(HIGHLIGHTS_NDCI, { show: false })
  assert.equal(hidden.show, false)
  assert.ok(hidden.notes.some((n) => n.key === 'map.pins.hidden'))
  assert.equal(hidden.items[0].chip, null, 'ndci pins carry no anomaly chip')
  assert.equal(hidden.items[0].z, null)
  assert.equal(hidden.shape, 'square')
  assertKeysExist(model, 'pins')
  assertKeysExist(hidden, 'pins ndci')
})

test('legend text by mode, worded exactly as specified', () => {
  assert.equal(pinLegendKey('ndci'), 'map.pins.legend_ndci')
  assert.equal(pinLegendKey('anomaly'), 'map.pins.legend_anomaly')
  assert.equal(pinLegendKey('risk'), null)
  assert.equal(pinLegendKey(undefined), null)
  assert.equal(pinShape('ndci'), 'square')
  assert.equal(pinShape('anomaly'), 'diamond')
  assert.equal(pinShape('x'), null)
  assert.equal(en.map.pins.legend_ndci, 'Highest NDCI in this scan (rank within one image) — not a risk level')
  assert.equal(en.map.pins.legend_anomaly, 'Anomaly vs own seasonal history, TEST baseline — not a risk level')
  assert.match(th.map.pins.legend_ndci, /ไม่ใช่ระดับความเสี่ยง$/)
  assert.match(th.map.pins.legend_anomaly, /\(TEST\).*ไม่ใช่ระดับความเสี่ยง$/)
})

test('pin count is clamped to the API range 3-10', () => {
  assert.equal(clampPinCount(5), 5)
  assert.equal(clampPinCount(1), 3)
  assert.equal(clampPinCount(42), 10)
  assert.equal(clampPinCount('7'), 7)
  assert.equal(clampPinCount(4.5), 5)
  assert.equal(clampPinCount(null), 5)
})

// ------------------------------------------------------------------ cell

test('cell model: a reading with its TEST anomaly block, every value the API sent', () => {
  const cell = buildCellModel(PIXEL_TEST)
  assert.equal(cell.state, 'reading')
  assert.equal(cell.chip.key, 'measured')
  assert.equal(cell.meaning, PIXEL_TEST.meaning)
  assert.deepEqual(cell.indices.map((r) => r.value.text), ['0.0976', '1.2162', '0.2086', '0.9600'])
  assert.equal(cell.indices[0].source.field, 'index_values.ndci')
  assert.equal(cell.acquiredDate.value.text, '2026-10-07')
  assert.equal(cell.acquiredAt.value.text, '2026-10-07 03:54Z')
  assert.equal(cell.cell.lat.raw, PIXEL_TEST.cell_lat)
  assert.equal(cell.centre.lat.raw, PIXEL_TEST.pixel_centre_lat)
  assert.equal(cell.scale.value.text, '200 m')
  assert.equal(cell.scale.note.key, 'map.cell.sampling')
  const rows = Object.fromEntries(cell.anomaly.rows.map((r) => [r.id, r.value]))
  assert.equal(rows.robust_z.raw, PIXEL_TEST.anomaly.robust_z)
  assert.equal(cell.anomaly.chip.key, 'anomaly_normal_test', 'even "normal" carries the TEST marker')
  assert.equal(cell.anomaly.reason, null)
  assert.equal(cell.anomaly.seasonKey, 'm10+-1')
  assert.equal(cell.anomaly.baselineVersion, 'TEST-20261009-9fc9a022')
  assert.deepEqual(cell.anomaly.bands.map((b) => b.value.text), ['444', '425', '408'])
  assert.match(cell.rawUrl, /\/raster-scan\/pixel\?lat=12\.69&lng=100\.355&run_id=6$/)
  assert.equal(cell.csv.filename, 'cell-run-6-r515-c246.csv')
  assert.match(cell.csv.content(), /anomaly\.robust_z/)
  assertKeysExist(cell, 'cell')
})

test('cell model: z is "—" with the server reason when not assessed; no block without anomaly', () => {
  const notAssessed = buildCellModel({
    ...PIXEL_TEST,
    anomaly: { ...PIXEL_TEST.anomaly, robust_z: null, level: null, reason: 'too_old' },
  })
  const z = notAssessed.anomaly.rows.find((r) => r.id === 'robust_z').value
  assert.equal(z.isNull, true)
  assert.equal(z.text, '—')
  assert.equal(z.reason, 'too_old')
  assert.equal(notAssessed.anomaly.chip.key, 'anomaly_not_assessed_test')
  assert.equal(buildCellModel({ ...PIXEL_TEST, anomaly: null }).anomaly, null)
  const unmeasured = buildCellModel({ ...PIXEL_TEST, state: 'not_measured', index_values: null, anomaly: null })
  assert.equal(unmeasured.state, 'not_measured')
  assert.equal(unmeasured.indices, null, 'no index row for a cell with no reading')
  assert.equal(buildCellModel({ ...PIXEL_TEST, state: 'added_later' }).state, 'not_measured')
  assert.equal(buildCellModel({ ...PIXEL_TEST, state: 'outside_study_area' }).state, 'outside')
})

// ------------------------------------------------------------------ rail

test('rail model: run provenance, selected scene ids, scene-date bars from the API shares', () => {
  const rail = buildRailModel({ raster: RASTER, request: {}, now: NOW })
  assert.deepEqual(rail.run.rows.map((r) => r.id), ['run_id', 'status', 'date_used', 'scale_m', 'completed_at', 'cell_count', 'scene_count'])
  const byId = Object.fromEntries(rail.run.rows.map((r) => [r.id, r]))
  assert.equal(byId.run_id.code, '6')
  assert.equal(byId.date_used.value.text, '2026-10-09')
  assert.equal(byId.completed_at.value.text, '2026-10-09 13:05Z')
  assert.equal(byId.scale_m.value.text, '200 m')
  assert.deepEqual(rail.run.sceneIds, RASTER.source_metadata.scene_ids)
  assert.equal(rail.run.sceneIdsSource.field, 'source_metadata.scene_ids')
  assert.equal(rail.chart.state, 'ready')
  assert.deepEqual(rail.chart.rows.map((r) => [r.date, r.share.text]), [
    ['2026-10-07', '77.6 %'], ['2026-09-29', '15.6 %'], ['2026-10-02', '6.8 %'],
  ])
  assert.equal(rail.chart.rows[0].width, RASTER.scene_dates[0].share * 100)
  assert.match(rail.chart.csv.content(), /2026-10-07,182486,0\.7755790726337711,6,GET \/raster-scan/)
  assert.equal(rail.latestScene.line.key, 'overview.scene.used', 'the same line as on the Overview')
  assert.equal(rail.poll.state, 'ready')
  const none = buildRailModel({ raster: { ...RASTER, scene_dates: null }, now: NOW })
  assert.equal(none.chart.state, 'empty')
  assert.equal(none.chart.empty.key, 'map.chart.none')
  const noRun = buildRailModel({ raster: { run_id: null, reason: 'No raster overlay has been rendered yet.' }, now: NOW })
  assert.equal(noRun.run.state, 'empty')
  assert.equal(noRun.run.serverReason, 'No raster overlay has been rendered yet.')
  assertKeysExist(rail, 'rail')
})

// ------------------------------------------------------------- permalink

test('permalink: lat/lng select the cell and fly to it; a pin of the served run is selected', () => {
  const cell = applyPermalink(readPermalink('?lat=12.69&lng=100.355&run=6&layer=true_color&zoom=13'), { raster: RASTER })
  assert.deepEqual(cell.selection, { kind: 'cell', lat: 12.69, lng: 100.355 })
  assert.deepEqual(cell.fly, { lat: 12.69, lng: 100.355, zoom: 13 })
  assert.equal(cell.layer, 'true_color')
  assert.equal(cell.zoom, 13)
  assert.deepEqual(cell.notes, [])
  const pin = applyPermalink(readPermalink('?pin=2&run=6'), { raster: RASTER })
  assert.deepEqual(pin.selection, { kind: 'pin', rank: 2 })
  assert.equal(pin.fly, null, 'a pin is flown to once the pins have loaded')
  assert.equal(pin.layer, 'ndci')
})

test('permalink: a run that is no longer served says so and loads the latest', () => {
  const gone = applyPermalink(readPermalink('?pin=3&run=2'), { raster: RASTER })
  assert.equal(gone.runGone, true)
  assert.equal(gone.selection, null, 'pins belong to one run')
  assert.deepEqual(gone.notes.map((n) => n.key), ['map.permalink.run_gone', 'map.permalink.pin_gone'])
  assert.deepEqual(gone.notes[0].params, { run: '2', latest: '6' })
  const t = createT('en')
  assert.equal(renderMessage(t, gone.notes[0]), 'The link named run 2, which is no longer the run served. Showing the latest run (6) instead; its values may differ.')
  const cellGone = applyPermalink(readPermalink('?lat=12.69&lng=100.355&run=2'), { raster: RASTER })
  assert.deepEqual(cellGone.selection, { kind: 'cell', lat: 12.69, lng: 100.355 }, 'the place is kept, read from the latest run')
  assert.equal(cellGone.notes[0].key, 'map.permalink.run_gone')
  const noRaster = applyPermalink(readPermalink('?run=2'), { raster: { run_id: null } })
  assert.equal(noRaster.notes[0].key, 'map.permalink.run_gone_none')
  // Before the raster has loaded nothing is claimed about the run.
  assert.deepEqual(applyPermalink(readPermalink('?run=2&pin=1'), { raster: null }).notes, [])
  const noRgb = applyPermalink(readPermalink('?layer=true_color'), { raster: { ...RASTER, true_color_url: null } })
  assert.equal(noRgb.layer, 'ndci')
  assert.equal(noRgb.notes[0].key, 'map.permalink.layer_unavailable')
  for (const m of [gone, cellGone, noRaster, noRgb]) assertKeysExist(m, 'permalink')
})

test('permalink: serialize writes the selection and view only, and round-trips', () => {
  const cell = serializeView({ selection: { kind: 'cell', lat: 12.6900004, lng: 100.355 }, layer: 'ndci', zoom: 12.5, runId: 6, lang: 'en' })
  assert.equal(cell, 'lat=12.69&lng=100.355&run=6&layer=ndci&zoom=12.5&lang=en')
  assert.deepEqual(decodeView(cell), { lat: 12.69, lng: 100.355, runId: 6, layer: 'ndci', zoom: 12.5, lang: 'en' })
  const pin = serializeView({ selection: { kind: 'pin', rank: 4 }, layer: 'light_map', zoom: null, runId: 6 })
  assert.equal(pin, 'run=6&layer=light_map&pin=4')
  assert.deepEqual(applyPermalink(decodeView(pin), { raster: RASTER }).selection, { kind: 'pin', rank: 4 })
  assert.equal(serializeView({ selection: null, layer: 'nope', runId: null }), '')
})
