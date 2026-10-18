// Pure geometry for the raster map's viewport: how much of the map the
// floating panels cover, and how far to pan so a station stays readable.
// No Leaflet, no DOM: callers pass pixel numbers measured from the page.

/** Half of a station dot (18 px) and the dot-to-label gap, as drawn in glass.css. */
export const DOT_RADIUS = 9
export const LABEL_GAP = 6

/** Padding is capped so the padded map never shrinks below 30% of its size. */
function capPair(a, b, size) {
  const budget = size * 0.7
  const total = a + b
  if (total <= budget || total === 0) return [a, b]
  const k = budget / total
  return [a * k, b * k]
}

/**
 * Padding for fitBounds with nothing selected.
 * @param {{mapW:number, mapH:number, railW?:number, topEdge?:number, dockH?:number, rightInset?:number}} m
 *   railW is the open rail's width (0 when closed or a drawer), topEdge the
 *   distance from the map top to below the header and top chips, dockH the
 *   bottom dock's height including its offset from the bottom edge.
 * @returns {{paddingTopLeft:[number,number], paddingBottomRight:[number,number]}}
 */
export function fitPadding({ mapW, mapH, railW = 0, topEdge = 180, dockH = 0, rightInset = 72 }) {
  const [left, right] = capPair(railW > 0 ? railW + 24 : 24, rightInset, mapW)
  const [top, bottom] = capPair(topEdge, dockH, mapH)
  return { paddingTopLeft: [Math.round(left), Math.round(top)], paddingBottomRight: [Math.round(right), Math.round(bottom)] }
}

/** Which side of its dot a label goes: left when the right side would pass `rightLimit`. */
export function labelSide({ x, labelW, rightLimit }) {
  return x + DOT_RADIUS + LABEL_GAP + labelW > rightLimit ? 'left' : 'right'
}

/**
 * How far the pin (and its label, when it has one) must move on screen to sit
 * inside `safe`, and which side the label takes. Picks the side needing the
 * smaller move; ties go right.
 * @param {{x:number, y:number, labelW?:number, safe:{left:number,right:number,top:number,bottom:number}}} p
 * @returns {{side:'left'|'right', shiftX:number, shiftY:number}} screen displacement wanted.
 */
export function revealShift({ x, y, labelW = 0, safe }) {
  const span = labelW > 0 ? LABEL_GAP + labelW : 0
  const shiftFor = (l, r) => {
    if (l < safe.left) return safe.left - l
    if (r > safe.right) return Math.max(safe.right - r, safe.left - l)
    return 0
  }
  const right = shiftFor(x - DOT_RADIUS, x + DOT_RADIUS + span)
  const left = shiftFor(x - DOT_RADIUS - span, x + DOT_RADIUS)
  const side = Math.abs(left) < Math.abs(right) ? 'left' : 'right'
  const top = y - DOT_RADIUS
  const bottom = y + DOT_RADIUS
  let shiftY = 0
  if (top < safe.top) shiftY = safe.top - top
  else if (bottom > safe.bottom) shiftY = Math.max(safe.bottom - bottom, safe.top - top)
  return { side, shiftX: side === 'left' ? left : right, shiftY }
}
