import test, { after, before } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { readFile } from 'node:fs/promises'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

let server
let RasterLayerControl
let RasterMapLayers
let RiskMap
let RasterLegendDock

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-raster-layer-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
    resolve: { alias: {
      'react-leaflet': fileURLToPath(new URL('./fixtures/leaflet.js', import.meta.url)),
      leaflet: fileURLToPath(new URL('./fixtures/leaflet_core.js', import.meta.url)),
    } },
  })
  const module = await server.ssrLoadModule('/src/components/RasterLayerSwitcher.jsx')
  RasterLayerControl = module.default
  RasterMapLayers = module.RasterMapLayers
  RasterLegendDock = (await server.ssrLoadModule('/src/components/RasterLegend.jsx')).RasterLegendDock
  RiskMap = (await server.ssrLoadModule('/src/components/RiskMap.jsx')).default
})

after(async () => server?.close())

const DATA = {
  bounds: [[12.5, 99.9], [13.6, 101.0]],
  overlay_url: '/raster-scan/overlay.png?run_id=12',
  true_color_url: '/raster-scan/true-color.png?run_id=12',
}

test('the selector exposes the exact three labels with one selected mode', () => {
  for (const selected of ['true_color', 'light_map', 'ndci']) {
    const html = renderToStaticMarkup(createElement(RasterLayerControl, {
      mode: selected,
      onModeChange() {},
      trueColorAvailable: true,
    }))
    assert.match(html, />True Color</)
    assert.match(html, />Light Map</)
    assert.match(html, />NDCI Raster</)
    // 2026-10 glass restyle: the two scan images first, the reference map last.
    assert.ok(html.indexOf('True Color') < html.indexOf('NDCI Raster'))
    assert.ok(html.indexOf('NDCI Raster') < html.indexOf('Light Map'))
    assert.equal((html.match(/aria-pressed="true"/g) || []).length, 1)
    assert.match(html, new RegExp(`data-layer-mode="${selected}"[^>]*aria-pressed="true"`))
  }
})

test('selecting a layer reports the requested mutually exclusive mode', () => {
  const selected = []
  const tree = RasterLayerControl({
    mode: 'light_map',
    onModeChange: (mode) => selected.push(mode),
    trueColorAvailable: true,
  })
  for (const button of tree.props.children) button.props.onClick()
  assert.deepEqual(selected, ['true_color', 'ndci', 'light_map'])
})

test('only the selected run-aligned overlay is mounted', () => {
  const lightMap = renderToStaticMarkup(createElement(RasterMapLayers, {
    mode: 'light_map', data: DATA,
  }))
  const trueColor = renderToStaticMarkup(createElement(RasterMapLayers, {
    mode: 'true_color', data: DATA,
  }))
  const ndci = renderToStaticMarkup(createElement(RasterMapLayers, {
    mode: 'ndci', data: DATA,
  }))

  assert.doesNotMatch(lightMap, /data-overlay-url=/)
  assert.match(trueColor, /true-color\.png\?run_id=12/)
  assert.doesNotMatch(trueColor, /\/overlay\.png/)
  assert.match(ndci, /\/overlay\.png\?run_id=12/)
  assert.doesNotMatch(ndci, /true-color\.png/)
})

test('the raster page uses Esri World Light Gray base and reference tiles with attribution', () => {
  const html = renderToStaticMarkup(createElement(RiskMap, { mode: 'raster' }))

  assert.match(html, /Canvas\/World_Light_Gray_Base\/MapServer\/tile/)
  assert.match(html, /Canvas\/World_Light_Gray_Reference\/MapServer\/tile/)
  assert.match(html, /Esri/)
  assert.match(html, /OpenStreetMap contributors/)
  assert.doesNotMatch(html, /tile\.openstreetmap\.org/)
  assert.doesNotMatch(html, /World_Imagery/)
})

test('historical runs without stored RGB disable True Color and explain why', () => {
  const html = renderToStaticMarkup(createElement(RasterLayerControl, {
    mode: 'ndci',
    onModeChange() {},
    trueColorAvailable: false,
  }))

  assert.match(html, /data-layer-mode="true_color"[^>]*disabled/)
  assert.match(html, /ไม่มีภาพสีธรรมชาติที่ตรงกับรอบสแกน/)
})

test('the selector and scan information cannot overlap at desktop or narrow widths', async () => {
  const css = await readFile(new URL('../src/styles/global.css', import.meta.url), 'utf8')
  assert.match(css, /\.raster-layer-switcher\s*\{[\s\S]*?top:\s*16px;[\s\S]*?left:\s*16px;/)
  assert.match(css, /\.raster-scan-banner\s*\{[\s\S]*?top:\s*174px;/)
  // Bottom edge must clear the bottom-left legend: 174 top + 190 legend
  // + 16 offset + 16 gap = 396, so the cap subtracts at least that.
  const cap = css.match(/\.raster-scan-banner\s*\{[\s\S]*?max-height:\s*([^;]+);/)[1]
  assert.match(cap, /calc\(100%\s*-\s*(\d+)px\)/)
  assert.ok(Number(cap.match(/calc\(100%\s*-\s*(\d+)px\)/)[1]) >= 396, `banner max-height ${cap} can overlap the legend`)
  assert.match(
    css,
    /@media \(max-width: 680px\)[\s\S]*?\.raster-scan-banner,[\s\S]*?\.raster-legend\s*\{[\s\S]*?position:\s*static;/,
  )
})

test('the switcher root is shielded from Leaflet native click, dblclick and scroll', () => {
  globalThis.__leafletShielded = []
  const tree = RasterLayerControl({
    mode: 'light_map', onModeChange() {}, trueColorAvailable: true,
  })
  const root = { tag: 'switcher-root' }
  assert.equal(typeof tree.ref, 'function', 'the root exposes no ref to attach the shield to')
  tree.ref(root)
  const kinds = globalThis.__leafletShielded.filter((s) => s.el === root).map((s) => s.kind)
  assert.deepEqual(kinds.sort(), ['click', 'scroll'])
  // Unmount passes null; it must not throw or shield anything.
  globalThis.__leafletShielded = []
  tree.ref(null)
  assert.equal(globalThis.__leafletShielded.length, 0)
})

test('the no-data caption shows in every layer mode where the pixel probe is active', () => {
  const legend = { value: { swatches: [], domain: [-0.05, 0.1] } }
  for (const mode of ['true_color', 'light_map', 'ndci']) {
    const html = renderToStaticMarkup(createElement(RasterLegendDock, {
      layerMode: mode, legend, hasRaster: true,
    }))
    assert.match(html, /พื้นที่โปร่งใสไม่มีค่าที่ใช้ได้/, `${mode}: caption missing`)
    assert.match(html, /ไม่ใช่ค่าดัชนีต่ำหรือค่าศูนย์/, `${mode}: not-low/zero wording missing`)
  }
  // Only NDCI mode carries the colour ramp.
  assert.match(renderToStaticMarkup(createElement(RasterLegendDock, {
    layerMode: 'ndci', legend, hasRaster: true,
  })), /raster-legend-ramp/)
  for (const mode of ['true_color', 'light_map']) {
    assert.doesNotMatch(renderToStaticMarkup(createElement(RasterLegendDock, {
      layerMode: mode, legend, hasRaster: true,
    })), /raster-legend-ramp/)
  }
})

test('no raster, no probe, no caption', () => {
  assert.equal(renderToStaticMarkup(createElement(RasterLegendDock, {
    layerMode: 'light_map', legend: null, hasRaster: false,
  })), '')
})
