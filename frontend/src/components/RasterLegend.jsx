/**
 * Legend for the raster overlay.
 *
 * Every colour shown here comes from the API, not from this file. The
 * value swatches are sampled by the renderer from the same ramp that
 * painted the image (`render.legend_swatches`). Re-deriving them in JavaScript
 * would be a second implementation, and a legend that drifts from the
 * picture is a quiet lie about what a colour means.
 *
 * The wording (i18n `map.legend.*`, Thai by default) is bound by the same
 * rule as the pins: this is an index reading, not a risk level, and
 * transparent means no usable reading -- never a low or zero value. The
 * colour is the NDCI reading, not an anomaly.
 */
import { useLang } from '../i18n/useLang.js'

// Shared by the NDCI legend and the caption-only dock, so the wording
// cannot differ between layer modes.
function NoDataCaption() {
  const { t } = useLang()
  return (
    <p className="raster-legend-transparent">
      {t('map.legend.transparent')}{' '}
      <strong>{t('map.legend.transparent_strong')}</strong>
    </p>
  )
}

/**
 * The legend for the raster page. The overlay PNG is transparent wherever
 * nothing was measured, and the pixel probe stays active in every layer
 * mode, so the "transparent is not low/zero" caption must be visible in
 * every mode -- not only beside the NDCI ramp.
 */
export function RasterLegendDock({ layerMode, legend, hasRaster }) {
  const { t } = useLang()
  if (layerMode === 'ndci' && legend) return <RasterLegend legend={legend} />
  if (!hasRaster) return null
  return (
    <div className="raster-legend glass" role="note" aria-label={t('map.legend.aria_caption')}>
      <NoDataCaption />
    </div>
  )
}

export default function RasterLegend({ legend }) {
  const { t } = useLang()
  if (!legend) return null
  const value = legend.value || {}
  const swatches = value.swatches || []
  const domain = value.domain || []

  return (
    <div className="raster-legend glass" role="note" aria-label={t('map.legend.aria')}>
      <div className="raster-legend-title">{t('map.legend.title')}</div>

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

      <p className="raster-legend-note">{t('map.legend.note')}</p>
    </div>
  )
}
