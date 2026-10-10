/**
 * The raster map moved from /raster to /map (dashboard spec §3). Old links
 * keep working, query string and hash included, so a shared permalink
 * still opens the same view. History `replace`: the old URL is not left
 * behind as a back-button step.
 */
import { Navigate, useLocation } from 'react-router-dom'

export default function LegacyRasterRedirect() {
  const { search, hash } = useLocation()
  return <Navigate to={{ pathname: '/map', search, hash }} replace />
}
