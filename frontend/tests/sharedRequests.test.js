import test from 'node:test'
import assert from 'node:assert/strict'
import { client, getRiskMap, getRasterScan } from '../src/api/client.js'

test('simultaneous reads of /risk-map and /raster-scan share one request each', async () => {
  const calls = []
  const original = client.get
  client.get = async (url) => {
    calls.push(url)
    return { data: { url } }
  }
  try {
    const a = await Promise.all([getRiskMap(), getRiskMap(), getRiskMap(), getRiskMap()])
    const b = await Promise.all([getRasterScan(), getRasterScan(), getRasterScan(), getRasterScan()])
    assert.deepEqual(calls, ['/risk-map', '/raster-scan'])
    assert.ok(a.every((x) => x.url === '/risk-map') && b.every((x) => x.url === '/raster-scan'))
  } finally {
    client.get = original
  }
})

test('a failed read is not kept: the retry asks again', async () => {
  const original = client.get
  let n = 0
  client.get = async () => {
    n += 1
    if (n === 1) throw new Error('boom')
    return { data: { ok: true } }
  }
  try {
    await new Promise((r) => setTimeout(r, 1600)) // let any earlier share window pass
    await assert.rejects(getRiskMap(), /boom/)
    assert.deepEqual(await getRiskMap(), { ok: true })
    assert.equal(n, 2)
  } finally {
    client.get = original
  }
})
