import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'

let server
let api

before(async () => {
  server = await createServer({
    configFile: false,
    cacheDir: 'node_modules/.vite-raster-run-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
  })
  api = await server.ssrLoadModule('/src/api/client.js')
})

after(async () => server?.close())

test('pixel lookup sends the displayed run with the clicked coordinates', async () => {
  const originalAdapter = api.client.defaults.adapter
  const requests = []
  api.client.defaults.adapter = async (config) => {
    requests.push(config)
    return { data: { run_id: config.params.run_id }, status: 200, statusText: 'OK',
      headers: {}, config }
  }
  try {
    await api.getRasterPixel(12.97, 100.01, 12)
    await api.getRasterPixel(12.97, 100.01, 13)
    assert.deepEqual(requests.map(({ url, params }) => ({ url, params })), [
      { url: '/raster-scan/pixel', params: { lat: 12.97, lng: 100.01, run_id: 12 } },
      { url: '/raster-scan/pixel', params: { lat: 12.97, lng: 100.01, run_id: 13 } },
    ])
  } finally {
    api.client.defaults.adapter = originalAdapter
  }
})
