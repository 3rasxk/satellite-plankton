# Calibration notes — read before implementing threshold calibration

Companion to `events.csv`. These are structural/methodology findings from
resolving the 12 `TODO` rows (2026-08-22) — not encoded as columns in
`events.csv` itself because they describe how to *use* the rows, not facts
about any single row. `bloom-detection` must read this before implementing
`src/thresholds.py`.

**Current status (2026-09-06):** all 14 events cannot be evaluated for
detection. Spectral-index anomaly scoring is explicitly disabled with
`z_score_status: not_computed_no_valid_baseline`; `z_scores` and every
`calibrated_*` value are null. th_010 has a real satellite reading, but
its former anomaly calculation mixed a dimensionless index with a MODIS
`chlor_a` concentration baseline. Its claimed miss is withdrawn. The
calibration methodology below is deferred until a valid statistic exists.

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
to effectively **11 iterations** (9 independent single events + 2
clusters treated as one unit each).

**Keep all rows separate in the per-event reporting table** (`event_table.md`)
for transparency — a reader should still see all 14 rows and their
individual "cannot be evaluated" status. Only the *calibration loop's* hold-out
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

## 6. Partial cluster coordinate match (added 2026-08-22)

Context: on 2026-08-22 the human maintainer sourced and confirmed real
coordinates for 7 of the 14 events (`events.csv` commit d9811d7),
including th_006 (member of the `chonburi_aug2019` cluster, §1) and
th_010 (member of the `chonburi_feb2020` cluster, §1). Their cluster-mates
— th_005/th_007, and th_009 — still have no coordinate. This is a case §1
did not originally cover: what happens in leave-one-out when a cluster is
only *partially* matchable?

**Deferred methodology:** a same-episode cluster would be reported `caught` in leave-one-out
if ANY of its matchable members' real z-score crosses the primary index's
cutoff — evaluated as a logical OR across whichever members actually
produced a real z-score, not decided independently per member and not
required to be unanimous.

**Reasoning:** the cluster-mates are multiple observations of the SAME
physical bloom (§1's own justification for holding them out together at
all), not independent trials. If the satellite reading at th_006's pixel
would have crossed the cutoff, that is real evidence the system would
have caught "the Aug 2019 Chonburi episode" — the fact that th_005 and
th_007's own sites have no coordinate to check independently does not
weaken that evidence about the same event. Requiring every member to
independently have a coordinate AND cross the cutoff would silently
change the claim being scored, from "was this physical event detectable"
to "did every observation site happen to have a documented coordinate AND
independently cross the cutoff" — a much stricter, less meaningful
question that has nothing to do with detection performance and everything
to do with which sites happened to get a Wikipedia/Wikidata coordinate.
The alternative (requiring unanimity, or averaging members' z-scores) was
considered and rejected: unanimity is not what "same event" implies
methodologically (a bloom can be patchy — one site crossing the threshold
while another site of the same bloom does not is a real, expected outcome
of a patchy bloom, not evidence the system failed at the second site),
and averaging would conflate two different signals' strengths with no
principled weighting between them for a single-index sweep.

A member without a valid anomaly statistic cannot count as a miss. At
present no member has one: `thresholds.leave_one_out` explicitly returns
`caught=None` for all 11 units and performs no threshold comparison.

Satellite availability remains a separate finding. th_006's candidate
scenes were all cloud-rejected. th_010 now has real bands and index values
on `actual_date` 2020-02-16 after the JRC/ETOPO1 mask correction; its old
water-mask failure was a defect, not a site property. Its reading remains
one event (`n=1`), `karenia_sp` rather than the B2/B3 *Noctiluca* target,
and dependent on the fallback at a turbid near-shore buffer. See
`LIMITATIONS.md` §1 for the complete reading qualifiers. Neither the
recovered reading nor any old invalid anomaly value is a hit or a miss.
