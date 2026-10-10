/**
 * An in-app link that works inside and outside the router: a react-router
 * `<Link>` (no reload) when a router is present, a plain `<a>` otherwise
 * (isolated renders and tests). Shared by the ui components that link to
 * /methods and /data.
 *
 * Limitations: for in-app paths only; external URLs use a plain `<a>`.
 */
import { Link, useInRouterContext } from 'react-router-dom'

export default function RouteLink({ to, children, ...rest }) {
  const inRouter = useInRouterContext()
  if (inRouter) return <Link to={to} {...rest}>{children}</Link>
  return <a href={typeof to === 'string' ? to : '#'} {...rest}>{children}</a>
}
