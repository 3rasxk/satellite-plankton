/**
 * Legend for the raster overlay.
 *
 * Every colour shown here comes from the API, not from this file. The
 * value swatches are sampled by the renderer from the same ramp that
 * painted the image (`render.legend_swatches`). Re-deriving them in JavaScript
 * would be a second implementation, and a legend that drifts from the
 * picture is a quiet lie about what a colour means.
 *
 * The wording is bound by the same rule as the pin ramp: this is an
 * index reading, not a risk level. No valid spectral-index baseline
 * exists, so nothing here ranks or classifies water.
 */
// Shared by the NDCI legend and the caption-only dock, so the wording
// cannot differ between layer modes.
function NoDataCaption() {
  return (
    <p className="raster-legend-transparent">
      พื้นที่โปร่งใสไม่มีค่าที่ใช้ได้ — เมฆบัง พื้นดิน หรือไม่มีภาพครอบคลุม
      <strong> ไม่ใช่ค่าดัชนีต่ำหรือค่าศูนย์</strong>
    </p>
  )
}

/**
 * Bottom-left legend area for the raster page. The overlay PNG is
 * transparent wherever nothing was measured, and the pixel probe stays
 * active in every layer mode, so the "transparent is not low/zero"
 * caption must be visible in every mode -- not only beside the NDCI ramp.
 */
export function RasterLegendDock({ layerMode, legend, hasRaster }) {
  if (layerMode === 'ndci' && legend) return <RasterLegend legend={legend} />
  if (!hasRaster) return null
  return (
    <div className="raster-legend glass" role="note" aria-label="คำอธิบายพื้นที่โปร่งใส">
      <NoDataCaption />
    </div>
  )
}

export default function RasterLegend({ legend }) {
  if (!legend) return null
  const value = legend.value || {}
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

      <NoDataCaption />

      <p className="raster-legend-note">
        แต่ละเซลล์คือพิกเซลจริง 1 จุด พร้อมวันที่ภาพของตัวเอง · ยังไม่มีการประเมินความผิดปกติ
      </p>
    </div>
  )
}
