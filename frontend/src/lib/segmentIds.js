/**
 * Element ids shared by a tab row (src/components/ui/Segmented.jsx,
 * kind="tabs") and the tab panels its caller renders, so `aria-controls`
 * and `aria-labelledby` always point at each other.
 */
export function tabId(idBase, value) {
  return `${idBase}-tab-${value}`
}

export function panelId(idBase, value) {
  return `${idBase}-panel-${value}`
}
