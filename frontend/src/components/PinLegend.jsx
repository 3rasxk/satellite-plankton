/**
 * PinLegend: the legend entry for the pins on the raster map (dashboard spec
 * §4.6; test-baseline spec §6).
 *
 * Data source: the pins' `mode` as the API returned it
 * (`/raster-scan/highlights` `mode`); the text is i18n
 * `map.pins.legend_ndci` -- "Highest NDCI in this scan (rank within one
 * image) — not a risk level" -- or `map.pins.legend_anomaly` -- "Anomaly vs
 * own seasonal history, TEST baseline — not a risk level", chosen by
 * `pinLegendKey` (src/lib/mapModel.js). A mode this UI does not know draws
 * no legend (its pins are not drawn either).
 *
 * The badge is the marker itself in miniature: dark neutral, numbered, a
 * square for NDCI pins and a diamond for TEST anomaly pins -- never a risk
 * colour and never the interaction accent. Shape is named in words too, so
 * colour and shape are never the only carriers.
 */
import { pinLegendKey, pinShape } from '../lib/mapModel.js'
import { useLang } from '../i18n/useLang.js'

export function PinBadge({ shape, rank, selected = false }) {
  return (
    <span className="pw-map-pin" data-shape={shape} data-selected={selected ? 'true' : undefined} aria-hidden="true">
      <span>{rank}</span>
    </span>
  )
}

export default function PinLegend({ mode }) {
  const { t } = useLang()
  const key = pinLegendKey(mode)
  const shape = pinShape(mode)
  if (!key) return null
  return (
    <p className="pw-map-pin-legend" data-mode={mode}>
      <PinBadge shape={shape} rank="1" />
      <span>
        <span className="pw-sr-only">{`${t(shape === 'diamond' ? 'map.pins.shape_anomaly' : 'map.pins.shape_ndci')}: `}</span>
        {t(key)}
      </span>
    </p>
  )
}
