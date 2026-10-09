/**
 * The two API calls the academic dashboard adds, and the client module's
 * import under plain Node (src/lib/provenance.js imports apiAssetUrl, so
 * client.js must load without Vite's import.meta.env).
 *
 * No network: axios is given an adapter that records the request.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { client, getMethods, getHighlights, apiAssetUrl } from '../src/api/client.js'

function recordRequests() {
  const calls = []
  const previous = client.defaults.adapter
  client.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, params: config.params })
    return { data: { echoed: config.url }, status: 200, statusText: 'OK', headers: {}, config }
  }
  return { calls, restore: () => { client.defaults.adapter = previous } }
}

test('getMethods: GET /methods, returns the body', async () => {
  const { calls, restore } = recordRequests()
  try {
    const data = await getMethods()
    assert.deepEqual(calls, [{ url: '/methods', method: 'get', params: undefined }])
    assert.deepEqual(data, { echoed: '/methods' })
  } finally { restore() }
})

test('getHighlights: GET /raster-scan/highlights with the given params', async () => {
  const { calls, restore } = recordRequests()
  try {
    await getHighlights({ n: 5, min_separation_m: 3000, mode: 'anomaly', run_id: 6 })
    await getHighlights()
    assert.deepEqual(calls, [
      { url: '/raster-scan/highlights', method: 'get', params: { n: 5, min_separation_m: 3000, mode: 'anomaly', run_id: 6 } },
      { url: '/raster-scan/highlights', method: 'get', params: {} },
    ])
  } finally { restore() }
})

test('apiAssetUrl works outside Vite (falls back to the dev base URL)', () => {
  assert.match(apiAssetUrl('/raster-scan'), /^https?:\/\/[^/]+\/raster-scan$|^\/api\/raster-scan$/)
  assert.equal(apiAssetUrl(null), null)
  assert.equal(apiAssetUrl('https://example.org/x.png'), 'https://example.org/x.png')
})
