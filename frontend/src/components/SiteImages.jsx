/**
 * SiteImages: the two cached images of one site's latest reading -- true
 * colour and the NDCI heatmap -- each as a numbered figure with its scene
 * date and cloud fraction (dashboard spec §4.3).
 *
 * Data source: `model.images` from src/lib/sitesModel.js, i.e. the
 * `/risk-map` feature's `true_color_image_url` / `ndci_heatmap_image_url`
 * (GET /risk-map/{site_id}/image?image_type=..., the scheduler's cached PNG
 * bytes, no live Earth Engine call) and the same reading's `actual_date`
 * and `cloud_fraction`. The PNG is fetched through the shared client
 * (hooks/useSatelliteImage.js, the same path as the reused SatelliteImage
 * component), so a failed request shows the server's own `detail` text
 * verbatim instead of a broken image.
 *
 * States: no URL -> the stated reason (the server's `image_status` when the
 * response carries one, else "no cached image", plus the site's own status
 * when it has no reading); loading -> a skeleton; error -> the server text.
 * The NDCI heatmap's colours are the NDCI reading only -- not an anomaly
 * and not a risk level.
 */
import FigureFrame from './ui/FigureFrame.jsx'
import Value from './ui/Value.jsx'
import { useSatelliteImage } from '../hooks/useSatelliteImage.js'
import { reasonKey } from '../lib/format.js'
import { useLang } from '../i18n/useLang.js'

function Absent({ absent }) {
  const { t } = useLang()
  const statusKey = absent.statusReason ? reasonKey(absent.statusReason) : null
  return (
    <div className="pw-site-image-absent" role="note">
      <p className="pw-site-image-absent-title">{t(absent.key)}</p>
      {absent.serverStatus && (
        <p>
          <span className="pw-label">{t('site.image.server_status')}</span>{' '}
          <code className="pw-mono" lang="en">{absent.serverStatus}</code>
        </p>
      )}
      {absent.statusReason && <p>{statusKey ? t(statusKey) : absent.statusReason}</p>}
      <p className="pw-site-image-absent-note">{t('site.image.absent_note')}</p>
    </div>
  )
}

function Picture({ image, alt }) {
  const { t } = useLang()
  const { loading, error, objectUrl } = useSatelliteImage(image.url)
  if (loading) {
    return (
      <div className="pw-site-image-frame" aria-busy="true">
        <div className="pw-site-image-skeleton" aria-hidden="true" />
        <p className="pw-ov-loading">{t('site.image.loading')}</p>
      </div>
    )
  }
  if (error) {
    return (
      <div className="pw-site-image-absent" role="status">
        <p className="pw-site-image-absent-title">{t('site.image.error')}</p>
        <p className="pw-label">{t('error.server_detail')}</p>
        <blockquote className="pw-server-text" lang="en">{error}</blockquote>
      </div>
    )
  }
  if (!objectUrl) return null
  return (
    <div className="pw-site-image-frame">
      <img className="pw-site-image" src={objectUrl} alt={alt} />
    </div>
  )
}

function ImageFigure({ image, siteName, number }) {
  const { t } = useLang()
  const kind = t(image.titleKey)
  const caption = (
    <>
      <span className="pw-site-image-kind">{kind}</span>
      {' · '}
      <span className="pw-label">{t('site.image.scene')}</span>{' '}
      <Value value={image.date.raw} spec={image.date.spec} source={image.dateSource} />
      {' · '}
      <span className="pw-label">{t('site.image.cloud')}</span>{' '}
      <Value value={image.cloud.raw} spec={image.cloud.spec} source={image.cloudSource} />
      {image.id === 'ndci_heatmap' && <span className="pw-site-image-note">{` ${t('site.image.ndci_note')}`}</span>}
    </>
  )
  const alt = t(image.altKey, { name: siteName, date: image.date.text })
  return (
    <FigureFrame number={number} caption={caption} source={image.source} flush className="pw-site-image-figure">
      {image.url ? <Picture image={image} alt={alt} /> : <Absent absent={image.absent} />}
    </FigureFrame>
  )
}

export default function SiteImages({ images, siteName, firstFigure = 1 }) {
  if (!Array.isArray(images) || images.length === 0) return null
  return (
    <div className="pw-cols-2 pw-site-images">
      {images.map((image, i) => (
        <ImageFigure key={image.id} image={image} siteName={siteName} number={firstFigure + i} />
      ))}
    </div>
  )
}
