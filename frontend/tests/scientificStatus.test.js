import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('the UI names the satellite-signal field without converting NDCI colours to risk', async () => {
  const [constants, ndciPage, legend, oldTexture] = await Promise.all([
    readFile(new URL('../src/constants.js', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/NdciPage.jsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/RasterLegend.jsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/utils/noiseField.js', import.meta.url), 'utf8'),
  ])

  assert.match(constants, /ระดับความผิดปกติของสัญญาณดาวเทียม/)
  assert.match(constants, /ไม่มีข้อมูลประเมิน/)
  assert.match(ndciPage, /SIGNAL_ANOMALY_LABEL_TH/)
  assert.match(legend, /ไม่ใช่ระดับความเสี่ยง/)
  assert.doesNotMatch(legend, /ความเสี่ยง(?:ต่ำ|ปานกลาง|สูง)|(?:low|medium|high) (?:bloom )?risk/i)
  assert.doesNotMatch(oldTexture, /severe bloom|bloom likely|NDCI\s*[<>]/i)
  assert.doesNotMatch(ndciPage, /chlorophyll-a\s*[≥>]\s*10|29\s*[–-]\s*30|1,?469/i)
})
