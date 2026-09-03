import { useState } from 'react'
import { useSatelliteImage } from '../hooks/useSatelliteImage.js'

/**
 * Modern satellite image card component.
 */
export default function SatelliteImage({
  trueColorUrl,
  ndciHeatmapUrl,
  noImageMessage,
  sceneDate,
  resolving = false,
}) {
  const hasBoth = !!trueColorUrl && !!ndciHeatmapUrl

  const [userMode, setUserMode] = useState(null)
  const mode =
    userMode === 'true_color' && trueColorUrl
      ? 'true_color'
      : userMode === 'ndci_heatmap' && ndciHeatmapUrl
        ? 'ndci_heatmap'
        : trueColorUrl
          ? 'true_color'
          : 'ndci_heatmap'

  const activeUrl = mode === 'true_color' ? trueColorUrl : ndciHeatmapUrl
  const { loading, error, objectUrl } = useSatelliteImage(activeUrl)

  return (
    <div className="detail-card">
      <div className="detail-card-header flex-between">
        <span className="detail-card-title">ภาพถ่ายดาวเทียม</span>
        {hasBoth && (
          <div className="satellite-pill-toggle" role="group" aria-label="Satellite image type">
            <button
              type="button"
              className={mode === 'true_color' ? 'active' : ''}
              onClick={() => setUserMode('true_color')}
            >
              True Color
            </button>
            <button
              type="button"
              className={mode === 'ndci_heatmap' ? 'active' : ''}
              onClick={() => setUserMode('ndci_heatmap')}
            >
              Chlorophyll Index
            </button>
          </div>
        )}
      </div>

      <div className="satellite-preview-container">
        {resolving ? (
          <div className="satellite-image-frame">
            <p className="no-rules">กำลังค้นหาภาพถ่ายดาวเทียม… อาจใช้เวลาสักครู่ (ดึงข้อมูลจริงจาก Sentinel-2)</p>
          </div>
        ) : !trueColorUrl && !ndciHeatmapUrl ? (
          <div className="status-banner satellite-no-image">
            <strong>ไม่มีภาพถ่ายดาวเทียม</strong>
            <p>{noImageMessage || 'ไม่มีข้อมูลภาพถ่ายดาวเทียมที่ใช้งานได้สำหรับพิกัดนี้'}</p>
          </div>
        ) : (
          <div className="satellite-image-frame">
            {loading && <p className="no-rules">กำลังประมวลผลภาพถ่ายดาวเทียม… อาจใช้เวลาสักครู่</p>}
            {error && (
              <div className="status-banner">
                <strong>ไม่สามารถแสดงภาพได้</strong>
                <p>{error}</p>
              </div>
            )}
            {!loading && !error && objectUrl && (
              <img
                className="satellite-image"
                src={objectUrl}
                alt={mode === 'true_color' ? 'ภาพสีจริง Sentinel-2' : 'Chlorophyll Index'}
              />
            )}
          </div>
        )}
      </div>

      <div className="detail-card-footer-info">
        <div className="satellite-scene-info mono">
          {mode === 'true_color' ? 'True colour' : 'Chlorophyll Index'} · ฉาก {sceneDate || 'ล่าสุด'}
        </div>
      </div>
    </div>
  )
}
