/**
 * /states: design-review page of every system state (design reference).
 * The cards are the same components the real pages use (StateViews.jsx);
 * the copy is fixed text, not data. Card 6's age is an example.
 */
import { NoReading, NoSignal, NotChecked, OutOfDate, Skeleton, Unreachable } from './StateViews.jsx'

const CARDS = [
  ['1 · Loading', <Skeleton key="a" />, 'Fetching the latest observations…', 'First load can take a few seconds. Stations appear as soon as they are ready.'],
  ['2 · Data service unreachable', <Unreachable key="b" onRetry={() => window.location.reload()} />, 'One plain message, one action', 'The last loaded map stays visible, marked “out of date”, if one exists.'],
  ['3 · No usable observation', <NoReading key="c" />, 'Hollow grey pin on the map', 'Panel suggests consulting neighbouring stations; revisits occur every few days.'],
  ['4 · No recent signal', <NoSignal key="d" />, 'Empty, and reassuring', 'Reads as a result, not a missing section.'],
  ['5 · Not checked yet', <NotChecked key="e" />, 'Appears after a restart', 'Pin shows hollow, same as “no reading”.'],
  ['6 · Out of date (refresh failed) · example', <OutOfDate key="f" />, 'Keeps the data, flags the age', 'Better than hiding the station or implying it is current.'],
]

export default function StatesPage() {
  return (
    <div className="gl-scroll">
      <div className="gl-page">
        <div>
          <h1>System states</h1>
          <p className="gl-page-sub">Each non-reading states what occurred, the likely cause and the next step — and never borrows a risk colour.</p>
        </div>
        <div className="gl-states">
          {CARDS.map(([tag, view, title, text]) => (
            <div className="gl-surface gl-state" key={tag}>
              <span className="gl-state-tag">{tag}</span>
              {view}
              <strong>{title}</strong>
              <p>{text}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
