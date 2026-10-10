import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('the UI names the satellite-signal field without converting NDCI colours to risk', async () => {
  const legend = await readFile(new URL('../src/components/RasterLegend.jsx', import.meta.url), 'utf8')
  // The legend's words moved to i18n (Task 4): the title it renders must
  // still deny a risk level in both languages.
  const { default: th } = await import('../src/i18n/th.js')
  const { default: en } = await import('../src/i18n/en.js')

  assert.match(legend, /t\('map\.legend\.title'\)/)
  assert.match(th.map.legend.title, /ไม่ใช่ระดับความเสี่ยง/)
  assert.match(en.map.legend.title, /not a risk level/)
  assert.doesNotMatch(legend, /ความเสี่ยง(?:ต่ำ|ปานกลาง|สูง)|(?:low|medium|high) (?:bloom )?risk/i)
})
