function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum))
}

export function getDraggedOverlayPosition(origin, start, current) {
  return {
    x: origin.x + current.x - start.x,
    y: origin.y - (current.y - start.y),
  }
}

export function clampOverlayPosition(position, containerSize, overlaySize, inset = 8) {
  return {
    x: clamp(position.x, inset, containerSize.width - overlaySize.width - inset),
    y: clamp(position.y, inset, containerSize.height - overlaySize.height - inset),
  }
}
