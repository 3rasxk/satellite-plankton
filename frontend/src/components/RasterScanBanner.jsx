/**
 * What the raster on screen actually is, in words.
 *
 * Data source: `GET /raster-scan` only (backend/src/routers/raster_scan.py),
 * which serves the metadata of the run whose overlay is being drawn --
 * the same run the legend and the click-to-inspect panel answer from.
 * Nothing here is computed from the picture, and nothing is computed
 * from data the API did not send: the per-acquisition-day breakdown is
 * `scene_dates`, recorded at scan time from the stored date band, and
 * the coverage figure is the renderer's own `measured_fraction`. This
 * file only formats and translates.
 *
 * Limitations, and why each of them is on screen rather than in a doc:
 *
 *   - One raster is a most-recent-wins mosaic, so it mixes acquisitions.
 *     A date RANGE cannot say how unevenly: the same "28 Aug - 7 Sep"
 *     describes a picture that is 61% one pass and one spread evenly
 *     across ten days. The per-day shares are shown for that reason.
 *   - Coverage is a share of the study POLYGON, land included -- the
 *     polygon is a boundary, not a water mask. It is not the share of
 *     water that was measured, and is not labelled as one.
 *   - The unmeasured remainder is cloud, land and "no scene covered it"
 *     together. The stored raster cannot separate them, so neither does
 *     this banner (LIMITATIONS.md, "Unmeasured is not zero").
 *   - A cell is ONE nearest-neighbour-sampled native pixel, not an
 *     average of the square it fills on screen (data-pipeline/src/raster.py,
 *     "Resolution, and what a cell actually is"). A feature smaller than
 *     the sampling interval is hit or missed outright rather than
 *     diluted, which makes a low reading weaker evidence than its
 *     confident block of colour suggests.
 *   - No risk tier and no presence/absence verdict. Without a TEST baseline
 *     there is no anomaly statistic either (no valid spectral-index
 *     baseline exists, CLAUDE.md §0/§1); with one in force (`isTest`) the
 *     closing note says the anomaly is TEST, against the location's own
 *     history and uncalibrated.
 *
 * Text: i18n `map.banner.*` (Thai by default, so a render without a
 * language provider reads exactly as before). Props: `isTest` switches the
 * closing note to its TEST wording; `compact` (the /map rail) drops what the
 * rail already carries -- the headline (the rail section has its own), the
 * per-day bar list (SceneDateChart draws it, with a data table) and the
 * server disclaimer (the map's truth bar shows it verbatim).
 */
import { useLang } from '../i18n/useLang.js'



// Sentinel-2's own native resolutions. The four indices are computed
// from 10 m bands (B2/B3/B4) and 20 m bands (B5/B6), so one coarse cell
// is a different fraction of each -- stated as two numbers rather than
// rounded into one that would be wrong for half the readings.
const NATIVE_M_10 = 10
const NATIVE_M_20 = 20

const STATUS_KEYS = {
  ok: 'map.banner.status_ok',
  no_data: 'map.banner.status_no_data',
  error: 'map.banner.status_error',
  running: 'map.banner.status_running',
}

/** Whole percent-with-one-decimal, e.g. 0.2571 -> "25.7". Null-safe:
 * a share that is not a number produces nothing rather than "NaN%". */
function pct(fraction) {
  return Number.isFinite(fraction) ? (fraction * 100).toFixed(1) : null
}

/** Thousands separators without depending on the runtime's locale data,
 * so the same number reads the same in every browser and in tests. */
function grouped(count) {
  return Number.isFinite(count) ? String(Math.round(count)).replace(/\B(?=(\d{3})+(?!\d))/g, ',') : null
}

/** Whole days between two "YYYY-MM-DD" strings (both parse as UTC
 * midnight, so this is exact and does not depend on the viewer's clock
 * or timezone). Null unless both dates are present and parse. */
function daysBefore(targetDate, sceneDate) {
  if (!targetDate || !sceneDate) return null
  const gap = (Date.parse(targetDate) - Date.parse(sceneDate)) / 86400000
  return Number.isFinite(gap) ? Math.round(gap) : null
}

/** How many native pixels one cell of `scaleM` was sampled from: one
 * pixel is kept out of this many. Only for a scale coarser than the
 * native one -- an equal or finer read samples nothing, and claiming a
 * ratio there would be arithmetic pretending to be a measurement. */
function sampleRatio(scaleM, nativeM) {
  if (!Number.isFinite(scaleM) || scaleM <= nativeM) return null
  return Math.round((scaleM / nativeM) ** 2)
}

function AgeOfImagery({ data }) {
  const { t } = useLang()
  const newestAge = daysBefore(data.date_used, data.newest_scene_date)
  const oldestAge = daysBefore(data.date_used, data.oldest_scene_date)
  return (
    <p>
      {t('map.banner.target_date')} <span className="mono">{data.date_used}</span>
      <br />
      {t('map.banner.newest')} <span className="mono">{data.newest_scene_date}</span>
      {Number.isFinite(newestAge) && ` ${t('map.banner.days_before', { n: newestAge })}`}
      {' · '}
      {t('map.banner.oldest')} <span className="mono">{data.oldest_scene_date}</span>
      {Number.isFinite(oldestAge) && ` ${t('map.banner.days_before', { n: oldestAge })}`}
      {/* The day the run itself was taken -- stated, not turned into an
          age, because an age would be measured against the viewer's own
          clock and would drift away from every other number here. */}
      {typeof data.completed_at === 'string' && (
        <>
          <br />
          {t('map.banner.completed')} <span className="mono">{data.completed_at.slice(0, 10)}</span> (UTC)
        </>
      )}
      <br />
      {t('map.banner.target_not_data')}
    </p>
  )
}

/** The distribution a date range cannot carry. Rendered whole -- every
 * day the run recorded, largest share first -- rather than topped and
 * tailed: a rolled-up "and 5 other days" would be the same hiding the
 * range already does, one level down. `showList` false keeps the summary
 * sentence and leaves the per-day bars to the rail's SceneDateChart. */
function SceneDateShares({ data, showList }) {
  const { t } = useLang()
  if (!Array.isArray(data.scene_dates) || data.scene_dates.length === 0) {
    return (
      <p className="raster-scan-banner-note">
        {t('map.banner.no_breakdown')}
        <strong> {t('map.banner.no_breakdown_strong')}</strong>
      </p>
    )
  }

  // The largest entry, found rather than assumed to be first. The API
  // documents and tests a largest-first order, but naming the wrong day
  // as the dominant one is precisely the kind of quiet misstatement this
  // banner exists to prevent, so it is not left resting on an ordering.
  const top = data.scene_dates.reduce((most, entry) => (entry.cells > most.cells ? entry : most))
  return (
    <>
      <p>
        {t('map.banner.days_count', { n: data.scene_dates.length })} · {t('map.banner.top_day')}{' '}
        <span className="mono">{top.date}</span>
        {Number.isFinite(top.share) && ` ${t('map.banner.top_share', { pct: pct(top.share) })}`}
        {Number.isFinite(data.scene_count) &&
          ` · ${t('map.banner.scenes_considered', { n: data.scene_count })}`}
      </p>
      {showList && (
        <>
          <ol className="raster-scan-day-list">
            {data.scene_dates.map((entry) => (
              <li key={entry.date}>
                <span className="mono">{entry.date}</span>
                <span
                  className="raster-scan-day-bar"
                  style={{ width: `${Math.max(1, (entry.share || 0) * 100)}%` }}
                  aria-hidden="true"
                />
                <span className="raster-scan-day-share mono">{pct(entry.share)}%</span>
                <span className="raster-scan-day-cells">{t('map.banner.cells_count', { n: grouped(entry.cells) })}</span>
              </li>
            ))}
          </ol>
          <p className="raster-scan-banner-note">{t('map.banner.range_note')}</p>
        </>
      )}
    </>
  )
}

/** Coverage, with its denominator named. A percentage whose denominator
 * is unstated is the failure this project keeps finding in its own past
 * work, so the sentence says "of the polygon, land included" every time
 * and never shortens to "of the area". */
function Coverage({ data }) {
  const { t } = useLang()
  const coverage = data.coverage
  if (!coverage || !Number.isFinite(coverage.measured_fraction)) {
    return <p className="raster-scan-banner-note">{t('map.banner.no_coverage')}</p>
  }
  return (
    <>
      <p>
        {t('map.banner.coverage', { pct: pct(coverage.measured_fraction), rest: pct(1 - coverage.measured_fraction) })}
      </p>
      <p className="raster-scan-banner-note">
        {t('map.banner.denominator')} <strong>{t('map.banner.denominator_strong')}</strong>{' '}
        {t('map.banner.denominator_rest')}
        {Number.isFinite(coverage.measured_pixels) && Number.isFinite(coverage.polygon_pixels) &&
          ` ${t('map.banner.pixels', { measured: grouped(coverage.measured_pixels), polygon: grouped(coverage.polygon_pixels) })}`}
      </p>
      <p className="raster-scan-banner-note">
        {t('map.banner.unmeasured')}
        <strong> {t('map.banner.unmeasured_strong')}</strong>
      </p>
    </>
  )
}

/** The sampling reality. Phrased from data-pipeline/src/raster.py's own
 * measurement: GEE resamples with nearest neighbour, so a coarse cell IS
 * one native pixel -- neither "an average" (it is not) nor "a sample of
 * the area" (it is one point, and the difference is what makes a small
 * feature hit-or-miss rather than diluted). */
function SamplingReality({ data }) {
  const { t } = useLang()
  const scaleM = data.scale_m
  const ratio10 = sampleRatio(scaleM, NATIVE_M_10)
  const ratio20 = sampleRatio(scaleM, NATIVE_M_20)
  return (
    <p className="raster-scan-banner-note">
      {t('map.banner.sampling_a')} <strong>{t('map.banner.sampling_strong')}</strong> {t('map.banner.sampling_b')}
      {Number.isFinite(scaleM) && ` ${t('map.banner.sampling_every', { m: scaleM })}`}
      {ratio10 && ` (${t('map.banner.ratio10', { n: grouped(ratio10) })}`}
      {ratio20 && ` ${t('map.banner.ratio20', { n: grouped(ratio20) })}`}
      {ratio10 && ')'}
      {' '}
      <strong>{t('map.banner.not_average')}</strong> · {t('map.banner.consequence')}
    </p>
  )
}

export default function RasterScanBanner({ data, loading, error, onRefresh, isTest = false, compact = false }) {
  const { t } = useLang()
  const hasRaster = Boolean(data?.run_id)

  return (
    <div className="raster-scan-banner info-callout glass" role="status" data-compact={compact ? 'true' : undefined}>
      {(!compact || onRefresh) && (
        <div className="raster-scan-banner-status-row">
          {!compact && <span className="headline">{t('map.banner.headline')}</span>}
          {onRefresh && (
            <button type="button" className="retry-btn" onClick={onRefresh} disabled={loading}>
              {loading ? t('map.banner.refreshing') : t('map.banner.refresh')}
            </button>
          )}
        </div>
      )}

      {loading && <p>{t('map.banner.loading')}</p>}

      {error && !loading && (
        <p>
          {t('map.banner.error')} <strong>{t('map.banner.error_strong')}</strong>{' '}
          {t('map.banner.error_rest')}
        </p>
      )}

      {!loading && !error && !hasRaster && (
        <p>{data?.reason || t('map.banner.no_raster')}</p>
      )}

      {hasRaster && (
        <>
          {data.status && <p>{STATUS_KEYS[data.status] ? t(STATUS_KEYS[data.status]) : data.status}</p>}

          {/* The picture on screen is not the newest attempt. Said before
              anything else about it, because every date below belongs to
              the older run. */}
          {data.stale_run_id != null && (
            <p className="raster-scan-banner-stale">
              {t('map.banner.stale', { stale_run: data.stale_run_id })}{' '}
              <strong>{t('map.banner.stale_strong', { run: data.run_id })}</strong>
            </p>
          )}

          <AgeOfImagery data={data} />
          <SceneDateShares data={data} showList={!compact} />
          <Coverage data={data} />
          <SamplingReality data={data} />

          <p>{t('map.banner.click_hint')}</p>
        </>
      )}

      {isTest ? (
        <>
          <p className="raster-scan-banner-note">
            {t('map.banner.test_only')} <strong>{t('map.banner.test_only_strong')}</strong>{' '}
            {t('map.banner.test_only_rest')}
          </p>
          <p>{t('map.banner.test_only_en')}</p>
        </>
      ) : (
        <>
          <p className="raster-scan-banner-note">
            {t('map.banner.index_only')} <strong>{t('map.banner.index_only_strong')}</strong>{' '}
            {t('map.banner.index_only_rest')}
          </p>
          <p>{t('map.banner.index_only_en')}</p>
        </>
      )}
      {!compact && data?.disclaimer && <p className="raster-scan-banner-note">{data.disclaimer}</p>}
    </div>
  )
}
