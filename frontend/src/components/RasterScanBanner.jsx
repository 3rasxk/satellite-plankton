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
 *   - No anomaly statistic, no risk tier, no presence/absence verdict:
 *     no valid spectral-index baseline exists (CLAUDE.md §0/§1).
 */

// Sentinel-2's own native resolutions. The four indices are computed
// from 10 m bands (B2/B3/B4) and 20 m bands (B5/B6), so one coarse cell
// is a different fraction of each -- stated as two numbers rather than
// rounded into one that would be wrong for half the readings.
const NATIVE_M_10 = 10
const NATIVE_M_20 = 20

const STATUS_LABEL_TH = {
  ok: 'สแกนสำเร็จ',
  no_data: 'ไม่มีภาพที่ใช้ได้ในรอบนี้',
  error: 'รอบสแกนล้มเหลว',
  running: 'กำลังสแกน — ภาพที่เห็นยังเป็นของรอบก่อนหน้า',
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

/** How many native pixels one cell of `scale_m` was sampled from: one
 * pixel is kept out of this many. Only for a scale coarser than the
 * native one -- an equal or finer read samples nothing, and claiming a
 * ratio there would be arithmetic pretending to be a measurement. */
function sampleRatio(scaleM, nativeM) {
  if (!Number.isFinite(scaleM) || scaleM <= nativeM) return null
  return Math.round((scaleM / nativeM) ** 2)
}

function AgeOfImagery({ data }) {
  const newestAge = daysBefore(data.date_used, data.newest_scene_date)
  const oldestAge = daysBefore(data.date_used, data.oldest_scene_date)
  return (
    <p>
      วันที่เป้าหมายการสแกน <span className="mono">{data.date_used}</span>
      <br />
      ภาพใหม่สุดในแรสเตอร์นี้ <span className="mono">{data.newest_scene_date}</span>
      {Number.isFinite(newestAge) && ` (ก่อนวันเป้าหมาย ${newestAge} วัน)`}
      {' · '}
      เก่าสุด <span className="mono">{data.oldest_scene_date}</span>
      {Number.isFinite(oldestAge) && ` (ก่อนวันเป้าหมาย ${oldestAge} วัน)`}
      {/* The day the run itself was taken -- stated, not turned into an
          age, because an age would be measured against the viewer's own
          clock and would drift away from every other number here. */}
      {typeof data.completed_at === 'string' && (
        <>
          <br />
          รอบนี้สแกนเมื่อ <span className="mono">{data.completed_at.slice(0, 10)}</span> (UTC)
        </>
      )}
      <br />
      วันที่เป้าหมายไม่ใช่วันที่ของข้อมูล — แต่ละเซลล์ถือวันที่ภาพของตัวเอง
    </p>
  )
}

/** The distribution a date range cannot carry. Rendered whole -- every
 * day the run recorded, largest share first -- rather than topped and
 * tailed: a rolled-up "and 5 other days" would be the same hiding the
 * range already does, one level down. */
function SceneDateShares({ data }) {
  if (!Array.isArray(data.scene_dates) || data.scene_dates.length === 0) {
    return (
      <p className="raster-scan-banner-note">
        รอบนี้ไม่ได้บันทึกสัดส่วนเซลล์รายวัน — ทราบเพียงช่วงวันที่ ไม่ทราบว่าวันไหนให้เซลล์เท่าใด
        <strong> ไม่ได้แปลว่ากระจายเท่า ๆ กัน</strong>
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
        เซลล์ที่เก็บไว้มีวันที่ถ่ายภาพ {data.scene_dates.length} วัน · วันที่ให้เซลล์มากที่สุดคือ{' '}
        <span className="mono">{top.date}</span>
        {Number.isFinite(top.share) && ` คิดเป็น ${pct(top.share)}% ของเซลล์ทั้งหมด`}
        {Number.isFinite(data.scene_count) &&
          ` · ภาพที่นำมาพิจารณา ${data.scene_count} ภาพ (บางภาพอาจไม่มีเซลล์เหลือในผลลัพธ์)`}
      </p>
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
            <span className="raster-scan-day-cells">{grouped(entry.cells)} เซลล์</span>
          </li>
        ))}
      </ol>
      <p className="raster-scan-banner-note">
        ช่วงวันที่อย่างเดียวไม่บอกว่าเซลล์ส่วนใหญ่มาจากวันไหน จึงแสดงสัดส่วนรายวันไว้ด้วย
      </p>
    </>
  )
}

/** Coverage, with its denominator named. A percentage whose denominator
 * is unstated is the failure this project keeps finding in its own past
 * work, so the sentence says "of the polygon, land included" every time
 * and never shortens to "of the area". */
function Coverage({ data }) {
  const coverage = data.coverage
  if (!coverage || !Number.isFinite(coverage.measured_fraction)) {
    return (
      <p className="raster-scan-banner-note">
        รอบนี้ไม่ได้บันทึกสัดส่วนพื้นที่ที่วัดได้ — ไม่รายงานตัวเลขที่ไม่ได้วัดไว้
      </p>
    )
  }
  return (
    <>
      <p>
        วัดค่าได้ {pct(coverage.measured_fraction)}% ของพื้นที่ในกรอบพื้นที่ศึกษา ·
        อีก {pct(1 - coverage.measured_fraction)}% ไม่มีค่าอ่าน
      </p>
      <p className="raster-scan-banner-note">
        ตัวหารคือพื้นที่ทั้งหมดในกรอบรูปหลายเหลี่ยม <strong>รวมแผ่นดินที่อยู่ในกรอบ</strong> —
        กรอบนี้เป็นขอบเขตพื้นที่ศึกษา ไม่ใช่หน้ากากน้ำ จึงไม่ใช่สัดส่วนของ “พื้นน้ำ”
        {Number.isFinite(coverage.measured_pixels) && Number.isFinite(coverage.polygon_pixels) &&
          ` (${grouped(coverage.measured_pixels)} จาก ${grouped(coverage.polygon_pixels)} พิกเซลของภาพซ้อนบนแผนที่)`}
      </p>
      <p className="raster-scan-banner-note">
        ส่วนที่ไม่มีค่าอ่านคือเมฆบัง แผ่นดิน หรือไม่มีภาพครอบคลุม รวมเป็นสถานะเดียวเพราะข้อมูลที่เก็บไว้แยกไม่ได้ ·
        <strong> ไม่ใช่ค่าดัชนีต่ำ และไม่ใช่ค่าศูนย์</strong>
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
  const scaleM = data.scale_m
  const ratio10 = sampleRatio(scaleM, NATIVE_M_10)
  const ratio20 = sampleRatio(scaleM, NATIVE_M_20)
  return (
    <p className="raster-scan-banner-note">
      หนึ่งเซลล์ = <strong>พิกเซลจริง 1 พิกเซล</strong> ที่เลือกมาแบบ nearest neighbour
      {Number.isFinite(scaleM) && ` ทุกระยะ ${scaleM} ม.`}
      {ratio10 && ` (สุ่มเก็บ 1 ใน ${grouped(ratio10)} พิกเซลของแบนด์ 10 ม.`}
      {ratio20 && ` และ 1 ใน ${grouped(ratio20)} ของแบนด์ 20 ม.`}
      {ratio10 && ')'}
      {' '}
      <strong>ไม่ใช่ค่าเฉลี่ยของช่องสี่เหลี่ยมที่เห็นบนจอ</strong> ·
      สิ่งที่เล็กกว่าระยะสุ่มจึงถูกเก็บมาทั้งก้อนหรือพลาดไปทั้งก้อน ไม่ได้ถูกเฉลี่ยจนจาง —
      เซลล์ที่ค่าต่ำจึงไม่ใช่หลักฐานเรื่องน้ำข้าง ๆ
    </p>
  )
}

export default function RasterScanBanner({ data, loading, error, onRefresh }) {
  const hasRaster = Boolean(data?.run_id)

  return (
    <div className="raster-scan-banner info-callout glass" role="status">
      <div className="raster-scan-banner-status-row">
        <span className="headline">ภาพแรสเตอร์ทั่วพื้นที่ศึกษา</span>
        {onRefresh && (
          <button type="button" className="retry-btn" onClick={onRefresh} disabled={loading}>
            {loading ? 'กำลังโหลด…' : 'โหลดผลล่าสุด'}
          </button>
        )}
      </div>

      {loading && <p>กำลังโหลดภาพแรสเตอร์…</p>}

      {error && !loading && (
        <p>
          โหลดภาพแรสเตอร์ไม่สำเร็จ — <strong>ไม่ได้แปลว่าไม่พบสาหร่าย</strong>{' '}
          แต่แปลว่ายังอ่านผลที่เก็บไว้ไม่ได้
        </p>
      )}

      {!loading && !error && !hasRaster && (
        <p>{data?.reason || 'ยังไม่มีภาพแรสเตอร์ — ต้องรันการสแกนก่อน'}</p>
      )}

      {hasRaster && (
        <>
          {data.status && <p>{STATUS_LABEL_TH[data.status] || data.status}</p>}

          {/* The picture on screen is not the newest attempt. Said before
              anything else about it, because every date below belongs to
              the older run. */}
          {data.stale_run_id != null && (
            <p className="raster-scan-banner-stale">
              มีรอบสแกนใหม่กว่า (รอบที่ {data.stale_run_id}) ที่ยังไม่มีภาพให้แสดง —
              กำลังสแกน ล้มเหลว หรือถูกลบตามอายุข้อมูล ·{' '}
              <strong>ภาพและตัวเลขทั้งหมดนี้เป็นของรอบที่ {data.run_id} ซึ่งเก่ากว่ารอบล่าสุด</strong>
            </p>
          )}

          <AgeOfImagery data={data} />
          <SceneDateShares data={data} />
          <Coverage data={data} />
          <SamplingReality data={data} />

          <p>คลิกบนแผนที่เพื่ออ่านค่าของเซลล์นั้นทีละเซลล์</p>
        </>
      )}

      <p className="raster-scan-banner-note">
        แสดงค่าดัชนีเท่านั้น <strong>ยังไม่มีการคำนวณค่าความผิดปกติ (anomaly)</strong> —
        ไม่มีค่าฐานของดัชนีที่ใช้ได้ จึงไม่มีระดับความเสี่ยง ไม่มีการจัดอันดับ
        และไม่มีคำตัดสินว่าพบหรือไม่พบสาหร่าย
      </p>
      <p>index values only — no anomaly detection active</p>
      {data?.disclaimer && <p className="raster-scan-banner-note">{data.disclaimer}</p>}
    </div>
  )
}
