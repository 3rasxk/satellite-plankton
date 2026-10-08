// Stand-in for the `leaflet` package itself (not react-leaflet): the real
// module touches `window` on import and cannot load under Node. Records
// which elements were shielded so a test can assert on them. Parked on
// globalThis for the same two-module-instances reason as leaflet.js.
const record = (kind) => (el) => {
  ;(globalThis.__leafletShielded ||= []).push({ kind, el })
  return el
}
const L = {
  DomEvent: {
    disableClickPropagation: record('click'),
    disableScrollPropagation: record('scroll'),
  },
}
export default L
