import { getSafeWatchColor } from '../utils/watchOverlay.js'

function valueOrDash(value, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : '—'
}

export default function WatchSitePopup({ alert }) {
  const siteAlert = alert ?? {}
  const levelColor = getSafeWatchColor(siteAlert.color, siteAlert.level)

  return (
    <div className="watch-site-popup">
      <strong>{siteAlert.name || '—'}</strong>
      <span className="watch-site-level">
        <span className="watch-site-level-swatch" style={{ backgroundColor: levelColor }} aria-hidden="true" />
        {siteAlert.label_th || '—'}
      </span>
      <dl>
        <dt>NDCI z-score</dt><dd>{valueOrDash(siteAlert.ndci_z)}</dd>
        <dt>เทรนด์ 14 วัน</dt><dd>{siteAlert.trend_rising ? 'เพิ่มขึ้น' : 'ข้อมูลไม่พอ/ไม่เพิ่มขึ้น'}</dd>
        <dt>ความชันต่อวัน</dt><dd>{valueOrDash(siteAlert.trend_slope_per_day, 4)}</dd>
        <dt>วันที่ใช้คำนวณเทรนด์</dt><dd>{siteAlert.trend_observations ?? '—'}</dd>
        <dt>วันที่ภาพ</dt><dd>{siteAlert.latest_scene_date || '—'}</dd>
        <dt>SST</dt><dd>{Number.isFinite(siteAlert.current_sst) ? `${siteAlert.current_sst.toFixed(2)} °C` : '—'}</dd>
        <dt>SST ตามฤดูกาล</dt><dd>{Number.isFinite(siteAlert.seasonal_sst) ? `${siteAlert.seasonal_sst.toFixed(2)} °C` : '—'}</dd>
        <dt>สถานะ SST</dt><dd>{siteAlert.sst_above_normal ? 'สูงกว่าปกติ' : 'ไม่สูงกว่าปกติ/ข้อมูลไม่พอ'}</dd>
        <dt>วันที่ SST</dt><dd>{siteAlert.sst_date || '—'}</dd>
      </dl>
      <small>สัญญาณเชิงกฎ ไม่ใช่การยืนยันแพลงก์ตอนบลูมหรือชนิดสิ่งมีชีวิต</small>
    </div>
  )
}
