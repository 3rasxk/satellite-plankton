import { useApi } from '../hooks/useApi.js'
import { getValidation, getMeta } from '../api/client.js'
import Icon from '../components/Icon.jsx'

/**
 * Reports & Exports page (design spec Screen 4: "รายงานและการส่งออก").
 *
 * Combines export actions (presentational — no download backend yet),
 * service status (partially real: GEE/FastAPI from GET /, others
 * presentational), scan history (presentational), and the existing
 * validation dataset callout (real data from /validation).
 *
 * Export buttons are intentionally presentational per current scope —
 * they render but don't fire downloads. The service-status section
 * shows real connectivity for GEE/FastAPI (same ping as the sidebar),
 * and presentational "ไม่ทราบสถานะ" for Scheduler/MODIS to avoid
 * fabricating a status that has no backing endpoint.
 */
export default function ReportsPage() {
  const validation = useApi(getValidation, [])
  const meta = useApi(getMeta, [])

  const apiConnected = !!meta.data && !meta.error

  const EXPORT_ITEMS = [
    {
      id: 'weekly_pdf',
      icon: 'file',
      title: 'รายงานสรุปรายสัปดาห์ (PDF)',
      detail: 'สรุปค่าดัชนี ระดับความเสี่ยง และสถานะรายจุดตรวจวัดในรอบ 7 วัน',
      action: 'สร้าง PDF',
    },
    {
      id: 'raw_csv',
      icon: 'chart',
      title: 'ข้อมูลค่าอ่านล่าสุด (CSV)',
      detail: 'ค่า NDCI และสถานะข้อมูลรายจุด — ยังไม่มีค่าความผิดปกติที่ถูกต้อง',
      action: 'ดาวน์โหลด CSV',
    },
    {
      id: 'events_csv',
      icon: 'clipboard',
      title: '14-Event Reference Dataset (CSV)',
      detail: 'ข้อมูลเหตุการณ์สาหร่ายพิษ 14 เหตุการณ์ จาก Luang-on et al. (2023) และแหล่งอื่น',
      action: 'ดาวน์โหลด CSV',
    },
    {
      id: 'scheduler_log',
      icon: 'wrench',
      title: 'Scheduler Log (JSON)',
      detail: 'บันทึกการทำงานของ scheduler ล่าสุด — สถานะรายรอบ เวลาเริ่ม/สิ้นสุด',
      action: 'ดาวน์โหลด JSON',
    },
  ]

  const SERVICE_STATUS = [
    {
      id: 'gee',
      name: 'Google Earth Engine',
      connected: apiConnected,
      label: apiConnected ? 'เชื่อมต่อแล้ว' : 'เชื่อมต่อไม่ได้',
    },
    {
      id: 'fastapi',
      name: 'FastAPI Backend',
      connected: apiConnected,
      label: apiConnected ? 'ทำงานปกติ' : 'ไม่ตอบสนอง',
    },
    {
      id: 'scheduler',
      name: 'Scheduler',
      connected: null,
      label: 'ไม่ทราบสถานะ',
    },
    {
      id: 'modis',
      name: 'MODIS Climatology',
      connected: null,
      label: 'ไม่ทราบสถานะ',
    },
  ]

  // Presentational scan history entries — no backend endpoint exists for
  // real scheduler logs yet. These are UI-layout demos only, marked as
  // presentational so nobody mistakes them for real system events.
  const SCAN_HISTORY = [
    { time: '—', message: 'ยังไม่มีบันทึกการสแกน (ข้อมูลตัวอย่าง)' },
  ]

  const v = validation.data

  return (
    <div className="page">
      <div className="page-header">
        <h1>รายงานและการส่งออก</h1>
        <span className="updated-line">
          ส่งออกข้อมูล ตรวจสอบสถานะระบบ และดูประวัติการสแกน
        </span>
      </div>

      {/* Export actions */}
      <section className="summary-section">
        <div className="section-title">การส่งออกข้อมูล</div>
        <div className="export-list">
          {EXPORT_ITEMS.map((item) => (
            <div key={item.id} className="export-item">
              <div className="export-item-icon" aria-hidden="true"><Icon name={item.icon} size={20} /></div>
              <div className="export-item-body">
                <div className="export-item-title">{item.title}</div>
                <div className="export-item-detail">{item.detail}</div>
              </div>
              <button type="button" className="export-item-btn" disabled>
                {item.action}
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Two-column row: Service Status + Scan History */}
      <div className="reports-two-col">
        <section className="summary-section">
          <div className="section-title">สถานะบริการ</div>
          <div className="service-status-card">
            {SERVICE_STATUS.map((svc) => (
              <div key={svc.id} className="service-status-row">
                <span
                  className="dot"
                  style={{
                    background:
                      svc.connected === true
                        ? 'var(--status-ok)'
                        : svc.connected === false
                          ? 'var(--status-error)'
                          : 'var(--no-data-line)',
                  }}
                />
                <span className="service-name">{svc.name}</span>
                <span className="service-label">{svc.label}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="summary-section">
          <div className="section-title">ประวัติการสแกน</div>
          <div className="scan-history-card">
            {SCAN_HISTORY.map((entry, i) => (
              <div key={i} className="scan-history-entry">
                <span className="mono scan-time">{entry.time}</span>
                <span className="scan-message">{entry.message}</span>
              </div>
            ))}
            <p className="no-rules" style={{ marginTop: 8 }}>
              บันทึกการสแกนจะแสดงเมื่อ scheduler ทำงานจริง
            </p>
          </div>
        </section>
      </div>

      {/* Validation dataset callout */}
      <section className="summary-section">
        <div className="section-title">ชุดข้อมูลอ้างอิง — เหตุการณ์สาหร่ายพิษในอดีต</div>

        {validation.loading && (
          <div className="state-panel">
            <h3>กำลังโหลดข้อมูล…</h3>
          </div>
        )}

        {validation.error && (
          <div className="state-panel error">
            <h3>ไม่สามารถเชื่อมต่อบริการข้อมูลได้</h3>
            <button type="button" className="retry-btn" onClick={validation.refetch}>
              ลองอีกครั้ง
            </button>
          </div>
        )}

        {v && (
          <div className="validation-callout">
            <span className="headline">
              {v.n_matchable} จาก {v.n_events} เหตุการณ์ มีพิกัดแม่นยำพอจะเทียบกับค่าอ่านดาวเทียม
            </span>
            <p>{v.calibration_caveat}</p>
            <div className="match-counts">
              <div className="match-count">
                <span className="n mono">{v.n_events}</span>
                <span className="label">เหตุการณ์ที่บันทึก</span>
              </div>
              <div className="match-count">
                <span className="n mono">{v.n_matchable}</span>
                <span className="label">มีพิกัดใช้ได้</span>
              </div>
              <div className="match-count">
                <span className="n mono">6</span>
                <span className="label">สายพันธุ์แพลงก์ตอน</span>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
