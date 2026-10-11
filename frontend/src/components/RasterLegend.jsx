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
import { formatValue } from '../lib/format.js'

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

/**
 * The map's NDCI colour bar (2026-10 glass dock): the API's own swatches as
 * one continuous bar, the domain ends in mono, and "Lower / Higher NDCI" --
 * NDCI is an optical index, not a chlorophyll concentration, so the ends
 * are never worded as chlorophyll. The no-data caption travels with it.
 * Shown only while the NDCI layer is on (the page shows the caption-only
 * dock in the other layers).
 */
export function NdciScaleBar({ legend }) {
  const { t } = useLang()
  const value = legend?.value || {}
  const swatches = (Array.isArray(value.swatches) ? value.swatches : []).filter((s) => typeof s?.hex === 'string')
  if (swatches.length === 0) return null
  const domain = Array.isArray(value.domain) && value.domain.length === 2 ? value.domain : null
  const stops = swatches.map((s, i) => `${s.hex} ${swatches.length === 1 ? 0 : (i / (swatches.length - 1)) * 100}%`).join(', ')
  return (
    <div className="pw-scale" role="note" aria-label={t('glass.scale.aria')}>
      <p className="pw-scale-title">{t('map.legend.title')}</p>
      <div className="pw-scale-bar" style={{ background: `linear-gradient(90deg, ${stops})` }} aria-hidden="true" />
      <div className="pw-scale-ends">
        <span><span className="pw-scale-word">{t('glass.scale.lower')}</span>{domain && <span className="pw-num">{`≤\u00a0${formatValue(domain[0], { kind: 'index' }).text}`}</span>}</span>
        <span><span className="pw-scale-word">{t('glass.scale.higher')}</span>{domain && <span className="pw-num">{`≥\u00a0${formatValue(domain[1], { kind: 'index' }).text}`}</span>}</span>
      </div>
      <p className="pw-scale-note">
        {t('map.legend.transparent')}{' '}
        <strong>{t('map.legend.transparent_strong')}</strong>
      </p>
    </div>
  )
}
