/**
 * What one clicked cell of the raster actually holds.
 *
 * Every number here comes from the API, which read it out of the stored
 * blob the overlay was drawn from (backend/src/raster_scan/pixel.py).
 * Nothing is computed in this file: no index is re-derived, no value is
 * inferred from a colour, and no reading is invented for a cell that has
 * none.
 *
 * The panel answers in the same three states the overlay paints, because
 * a difference a viewer can see on the map has to be a difference they
 * can read in words:
 *
 *   reading             the four index values and THIS cell's own
 *                       acquisition date
 *   not_measured        inside the study area, nothing usable here --
 *                       cloud, land, or no scene covered it. Never shown
 *                       as a number, and never as zero: an unmeasured
 *                       cell downloads as 0.0 and 0.0 is also a real NDCI
 *                       reading, so displaying one for the other is this
 *                       project's cardinal overclaim in words.
 *   outside_study_area  nothing was ever looked at here.
 *
 * Only a state of exactly "reading" produces numbers; every other value,
 * including one this build does not recognise, is shown as unmeasured.
 * The default has to fall that way -- an unknown state rendered through
 * the value table would print whatever `index_values` held, and for a
 * masked cell that is 0.0.
 *
 * Bound by the same rule as the legend and the pin ramp: these are index
 * readings, not risk levels. No valid spectral-index baseline exists, so
 * nothing here ranks or classifies water (CLAUDE.md §0/§1).
 */

// Display names only. The API's band keys are the raster's own
// (ndci/bda2/bda3/b2_b3); these are the labels the rest of the dashboard
// already uses for the same four quantities.
const BAND_LABELS = {
  ndci: 'NDCI',
  bda2: '2BDA',
  bda3: '3BDA',
  b2_b3: 'B2/B3',
}

// Four decimals: enough to tell two neighbouring cells apart, and a
// display choice only -- the API carries the stored value unrounded.
const DECIMALS = 4

export default function RasterPixelPanel({ pixel, loading, error, onClose }) {
  if (!loading && !error && !pixel) return null

  return (
    <div className="raster-pixel-panel glass" role="region" aria-label="ค่าที่วัดได้ของเซลล์ที่เลือก">
      <div className="raster-pixel-head">
        <span className="raster-pixel-title">ค่าดัชนีของเซลล์ที่เลือก</span>
        {onClose && (
          <button type="button" className="raster-pixel-close" onClick={onClose} aria-label="ปิด">
            ×
          </button>
        )}
      </div>

      {loading && <p className="raster-pixel-note">กำลังอ่านค่าจากเซลล์ที่เก็บไว้…</p>}

      {error && (
        <p className="raster-pixel-note">
          อ่านค่าเซลล์ไม่สำเร็จ — <strong>ไม่ได้แปลว่าไม่พบสาหร่าย</strong> แต่แปลว่ายังอ่านข้อมูลที่เก็บไว้ไม่ได้
        </p>
      )}

      {!loading && !error && pixel && <PixelBody pixel={pixel} />}
    </div>
  )
}

function PixelBody({ pixel }) {
  if (pixel.state === 'outside_study_area') {
    return (
      <p className="raster-pixel-note">
        นอกพื้นที่ศึกษา — ไม่ได้ตรวจวัดจุดนี้ จึงไม่มีค่าใด ๆ ให้รายงาน
      </p>
    )
  }

  // Anything that is not positively a reading is drawn as "not measured".
  // The test is on `state === 'reading'`, not on `state === 'not_measured'`,
  // so the safe direction is the default: a state this build has never
  // heard of says "we have no reading here" rather than falling through to
  // a table that would print whatever `index_values` happened to hold.
  if (pixel.state !== 'reading') {
    return (
      <>
        <p className="raster-pixel-note">
          ไม่ได้วัดค่าที่จุดนี้ — เมฆบัง พื้นดิน หรือไม่มีภาพถ่ายครอบคลุม{' '}
          <strong>ไม่ใช่ค่าดัชนีต่ำ และไม่ใช่ค่าศูนย์</strong>
        </p>
        <p className="raster-pixel-note">
          ทั้งสามสาเหตุแยกจากกันไม่ได้จากข้อมูลที่เก็บไว้ จึงรายงานรวมเป็นสถานะเดียว
        </p>
      </>
    )
  }

  const values = pixel.index_values || {}

  return (
    <>
      <dl className="raster-pixel-values">
        {Object.keys(BAND_LABELS).map((band) => (
          <div className="raster-pixel-value" key={band}>
            <dt>{BAND_LABELS[band]}</dt>
            <dd className="mono">
              {typeof values[band] === 'number'
                ? values[band].toFixed(DECIMALS)
                : 'คำนวณไม่ได้'}
            </dd>
          </div>
        ))}
      </dl>

      <p className="raster-pixel-meta">
        ภาพถ่ายของเซลล์นี้ <span className="mono">{pixel.acquired_date}</span> · พิกัดพิกเซลที่วัดจริง{' '}
        <span className="mono">
          {pixel.cell_lat?.toFixed(5)}, {pixel.cell_lng?.toFixed(5)}
        </span>
      </p>

      <p className="raster-pixel-note">
        แต่ละเซลล์คือพิกเซลจริง 1 จุด (~{pixel.scale_m} ม.) พร้อมวันที่ภาพของตัวเอง ไม่ใช่ค่าเฉลี่ยของทั้งช่อง ·
        เป็น<strong>ค่าดัชนี ไม่ใช่ระดับความเสี่ยง</strong> — ยังไม่มีการประเมินความผิดปกติ
      </p>
    </>
  )
}
