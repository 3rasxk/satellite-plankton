# Calibration notes — read before implementing threshold calibration

Companion to `events.csv`. These are structural/methodology findings from
resolving the 12 `TODO` rows (2026-08-22) — not encoded as columns in
`events.csv` itself because they describe how to *use* the rows, not facts
about any single row. `bloom-detection` must read this before implementing
`src/thresholds.py`.

## 1. Same-episode clusters — hold out together in leave-one-out

Two clusters are the same physical bloom observed at multiple sites/dates,
not independent samples:

- **th_005, th_006, th_007** — 19–29 Aug 2019, Wonnapha Beach/Laem Thaen,
  Koh Loy, Tham Phang Beach (all Chonburi), all `noctiluca_scintillans`.
  th_005's date range (19–29 Aug) contains th_006/th_007's exact date
  (27 Aug).
- **th_009, th_010** — 11–20 Feb 2020, Phli Pier Bridge and Ang Sila
  (both Chonburi), both `karenia_sp`, identical date range.

**Requirement:** in the leave-one-out loop, hold out each cluster as a
single unit (all its rows in, or all its rows out, together) — never hold
out one member while the others remain in the calibration set. Holding out
th_006 alone while th_005/th_007 stay in leaks information about the same
event into the "held-out" test. This changes the loop from 14 iterations
to effectively **12 iterations** (10 independent single events + 2
clusters treated as one unit each).

**Keep all rows separate in the per-event reporting table** (`event_table.md`)
for transparency — a reader should still see all 14 rows and their
individual flag/no-flag result. Only the *calibration loop's* hold-out
logic groups them; the report does not.

## 2. Species range beyond *Noctiluca scintillans* — report species per event

8 distinct taxa across the 14 events (only th_001, th_002(unknown),
th_003–th_007 are `noctiluca_scintillans`). The B2/B3 green-*Noctiluca*
discrimination feature (`docs/DETECTION_PLAN.md` §2) is *Noctiluca*-specific
and should not be expected to behave the same way, or fire at all, on
th_008 (`ceratium_furca`), th_009/th_010 (`karenia_sp`), th_011
(`leptocylindrus_sp`, a diatom), th_012 (mixed `noctiluca_miliaris,
ceratium_furca`), th_013 (`trichodesmium_erythraeum`, a cyanobacterium),
or th_014 (`suspected protogonyaulax sp.`).

**Requirement:** `event_table.md` must show the `species` column alongside
flagged/not-flagged, so a diatom miss isn't visually indistinguishable from
a *Noctiluca* miss — they are different claims about what the system can
detect.

## 3. th_012, th_013, th_014 — historical confirmation, not calibration points

Pre-monitoring-era (1981–1983), no cell count in any source, and per
`data/validation/thailand/seafdec_literature/SOURCE.md` these exist "only
as historical confirmation that red tide events have occurred," not as
quantitative labels. th_014 additionally carries an explicitly unresolved
casualty-count discrepancy between its two cross-referenced sources.

**Requirement:** these three may still be run through the pipeline like
any other row (for completeness in the 14-row table), but must not be
weighted the same as the 9 cell-count-bearing events when choosing an
operating point, and any false-negative on these three should not be
reported without noting their evidentiary weakness.

## 4. Date precision — four tiers, carry into the per-event table

- Exact single day: th_006, th_007, th_011 (and th_001).
- Exact day-range: th_005, th_009, th_010, th_012, th_014.
- Month expanded to full-month range: th_003, th_004, th_008.
- Multi-month range: th_013.

**Requirement:** `event_table.md` should surface this precision tier (or
the raw `date_start`/`date_end` window width) alongside each result — a
full-month search window has a much higher chance of finding *some*
cloud-free scene, but much lower confidence that scene coincides with peak
bloom. A flag on a month-wide window is a weaker claim than a flag on an
exact date.

## 5. `cell_count` — literal text, never silently parsed to one number

Stored as a single number (th_001, th_007, th_011), a literal range string
like `"684-8700"` (th_003–th_006, th_008–th_010), or blank where the source
gave none (th_002, th_012, th_013, th_014).

**Requirement:** `thresholds.py` must make an explicit, visible decision
for range values — lower bound, upper bound, or treat-as-wide-uncertainty —
not silently take e.g. the first number via string parsing. State the
choice and reasoning in a comment, same as the operating-point choice
itself (per `docs/DETECTION_PLAN.md` §4).
