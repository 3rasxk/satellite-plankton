import test from 'node:test'
import assert from 'node:assert/strict'

test('all monitored sites remain visible when risk is not evaluated', async () => {
  let selectMapFeatures
  try {
    ;({ selectMapFeatures } = await import('../src/utils/mapFeatures.js'))
  } catch {
    // The red phase intentionally reaches this branch until the helper exists.
  }

  assert.equal(typeof selectMapFeatures, 'function')
  const features = [
    { properties: { site_id: 'no-data', status: 'no_imagery', risk_level: null } },
    { properties: { site_id: 'index-only', status: 'ok', risk_level: null } },
    { properties: { site_id: 'alert', status: 'ok', risk_level: 'warning' } },
  ]

  assert.deepEqual(selectMapFeatures(features), features)
})
