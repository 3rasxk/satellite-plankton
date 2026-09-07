/**
 * Legend for the raster overlay.
 *
 * Every colour shown here comes from the API, not from this file. The
 * value swatches are sampled by the renderer from the same ramp that
 * painted the image (`render.legend_swatches`), and the no-data hatch
 * colours are the ones actually drawn. Re-deriving either in JavaScript
 * would be a second implementation, and a legend that drifts from the
 * picture is a quiet lie about what a colour means.
 *
 * The wording is bound by the same rule as the pin ramp: this is an
 * index reading, not a risk level. No valid spectral-index baseline
 * exists, so nothing here ranks or classifies water.
 */
const HATCH_SWATCH_SIZE = 34

function rgba(values) {
  if (!Array.isArray(values) || values.length < 4) return 'transparent'
  const [r, g, b, a] = values
  return `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`
}

export default function RasterLegend({ legend }) {
  if (!legend) return null
  const value = legend.value || {}
  const noData = legend.no_data || {}
  const swatches = value.swatches || []
  const domain = value.domain || []

  return (
    <div className="raster-legend glass" role="note" aria-label="คำอธิบายสัญลักษณ์แผนที่แรสเตอร์">
      <div className="raster-legend-title">ค่าดัชนี NDCI (ไม่ใช่ระดับความเสี่ยง)</div>

      <div className="raster-legend-ramp">
        {swatches.map((swatch) => (
          <span
            key={swatch.value}
            className="raster-legend-chip"
            style={{ background: swatch.hex }}
            title={`NDCI ${swatch.value.toFixed(3)}`}
          />
        ))}
      </div>
      {domain.length === 2 && (
        <div className="raster-legend-scale mono">
          <span>{domain[0]}</span>
          <span>{domain[1]}</span>
        </div>
      )}

      <div className="raster-legend-row">
        <span
          className="raster-legend-hatch"
          style={{
            width: HATCH_SWATCH_SIZE,
            backgroundColor: rgba(noData.base_rgba),
            backgroundImage: `repeating-linear-gradient(45deg, ${rgba(noData.stripe_rgba)} 0 2px, transparent 2px 5px)`,
          }}
        />
        <span>ไม่ได้วัดค่า — เมฆบัง พื้นดิน หรือไม่มีภาพครอบคลุม <strong>ไม่ใช่ค่าดัชนีต่ำ</strong></span>
      </div>

      <div className="raster-legend-row">
        <span className="raster-legend-outside" style={{ width: HATCH_SWATCH_SIZE }} />
        <span>นอกพื้นที่ศึกษา — ไม่ได้ตรวจวัด</span>
      </div>

      <p className="raster-legend-note">
        แต่ละเซลล์คือพิกเซลจริง 1 จุด พร้อมวันที่ภาพของตัวเอง · ยังไม่มีการประเมินความผิดปกติ
      </p>
    </div>
  )
}
