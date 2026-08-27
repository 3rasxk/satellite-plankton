# Task 7 fix report

## Changed files

- `frontend/src/components/RiskMap.jsx`: removed all legacy monitoring markers and feature fitting; fits the supplied scan bounds on mount and resize.
- `frontend/src/pages/OverviewPage.jsx`: always renders the map shell, regardless of `/risk-map` data availability.
- `frontend/src/components/RiskLegend.jsx`: hides the old point-risk legend for True Color while preserving NDCI and Watch legends.
- `frontend/src/utils/mapBounds.js` and `frontend/tests/mapBounds.test.js`: calculate the lower zoom limit with `getBoundsZoom(bounds, false)`.
- `frontend/src/styles/global.css`: removed the obsolete marker-only styles.
- `docs/superpowers/plans/2026-08-27-upper-gulf-ndci-watch-overlay.md`: records the revised Task 7 scope and verification.

## TDD evidence

- RED: `npm test -- mapBounds.test.js` failed because `syncMinimumBoundsZoom` passed `inside=true` while the regression test required `false`.
- GREEN: after the minimal utility change, the focused test and the complete frontend test suite passed.

## Verification

- `npm test` — 3 passed
- `npm run lint` — passed
- `npm run build` — passed
- `git diff --check` — passed

## Self-review

- Confirmed no `CircleMarker`, `FitToFeatures`, `makeAccessible`, `risk-marker`, or `featureCollection` references remain in Overview map components/pages.
- Confirmed the full original bounds are used as initial bounds, resize fit target, minimum-zoom target, and maximum bounds.
- Confirmed Watch tiles, illustrative NDCI, zoom controls, and the no-right-panel layout remain intact.
