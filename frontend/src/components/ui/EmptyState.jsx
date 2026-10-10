/**
 * EmptyState: a block that has nothing to show, saying why (dashboard spec
 * §10 "empty/unknown" state, and the temporary page placeholders).
 *
 * Data source: the caller's i18n text. `kind` ('empty' | 'placeholder' |
 * 'not_found' | 'unknown') only changes the frame; the words carry the
 * meaning. An empty block must explain what "nothing" means here -- not
 * measured is not the same as low -- so `body` is expected, not optional
 * decoration.
 */
import Icon from '../Icon.jsx'

const HEADING_TAGS = Object.freeze({ 2: 'h2', 3: 'h3', 4: 'h4' })

export default function EmptyState({ title, body, kind = 'empty', icon = 'grid', level = 2, action, children }) {
  const Heading = HEADING_TAGS[level] ?? 'h2'
  return (
    <section className="pw-state" data-kind={kind}>
      <span className="pw-state-icon"><Icon name={icon} size={20} strokeWidth={1.7} /></span>
      <div className="pw-state-body">
        <Heading className="pw-state-title">{title}</Heading>
        {body && <p>{body}</p>}
        {children}
        {action && <div className="pw-state-actions">{action}</div>}
      </div>
    </section>
  )
}
