# Detection & Prediction Plan — Physics-Based Algal Bloom System

Replaces the earlier ML training plan. Read alongside `.claude/agents/bloom-detection.md`.

---

## 0. Why physics, not machine learning

The supervised ML route was abandoned after the data search returned a hard result: across HAEDAT, FWC Florida, HABSOS and PMN (836,008 rows), there are **zero usable Thailand coastal records in the satellite era**. A second, Thailand-specific search recovered only **14 hand-extracted events (1981–2020)**, most described by place-name rather than coordinates.

Three consequences forced the pivot:

1. **No Thai labels means no Thai validation.** A model pretrained on Florida *Karenia brevis* would run on the Gulf of Thailand, but its accuracy there would be unmeasurable — an unverifiable number is not a result.
2. **Species mismatch is not a minor domain gap.** Florida's *K. brevis* is a photosynthetic dinoflagellate. The Gulf's green *Noctiluca scintillans* is non-photosynthetic and green because of an endosymbiont it carries. Their optical signatures differ at the mechanism level, so the very thing a classifier learns from Florida is the thing that doesn't transfer.
3. **Self-labelling is circular.** Deriving labels from a MODIS threshold and then training on MODIS-derived features teaches a model to reproduce a threshold we chose ourselves. Splitting 70/30 does not fix this — both halves inherit the same synthetic ground truth.

Physics has none of these problems. Spectral indices are standard, published, reproducible, need no labels, and work identically in every ocean.

**The 14 Thai events keep their role** — not as training data, but as the independent ground truth the whole system is validated against.

---

## 1. What the system does

Two functions, clearly separated. Never blur them.

| Function | Question answered | Confidence |
|----------|------------------|------------|
| **Detection** | Is there an anomalous chlorophyll signal right now? | High — this is standard remote sensing |
| **Prediction** | Are conditions trending toward a bloom over the coming days? | Lower — rule-based, must be labelled as indicative |

---

## 2. Detection — spectral indices

### The indices

| Index | Formula (Sentinel-2) | Role |
|-------|---------------------|------|
| **NDCI** | `(B5 − B4) / (B5 + B4)` | Primary chlorophyll proxy |
| **2BDA** | `B5 / B4` | Simple alternate |
| **3BDA** | `(1/B4 − 1/B5) × B6` | Turbid-water variant — likely the best fit for the upper Gulf near river mouths |
| **OC3/OC4** | blue/green band ratio | NASA's own algorithm, already applied in the MODIS `chlor_a` product |

Implement all three Sentinel-2 indices, swappable via config, and compare them against the 14 events rather than assuming NDCI wins.

### Green *Noctiluca* discrimination

Green *Noctiluca* shows elevated reflectance across roughly 440–550 nm relative to diatom blooms and non-bloom water. Add a B2/B3 ratio feature to separate a green bloom from a generic chlorophyll rise. Treat this as a secondary, lower-confidence signal — it is less established than NDCI itself.

### Anomaly, not raw value

A high index reading alone is not a bloom — some areas are simply productive. What matters is the departure from normal:

```
anomaly = index_today − climatology(location, day_of_year)
```

The climatology comes from the MODIS `chlor_a` archive (2002–present), averaged per location per time of year. This is what makes MODIS load-bearing in the design even though Sentinel-2 does the fine detection.

Express the anomaly in standard deviations (a z-score) so thresholds are comparable across locations with different baseline productivity.

---

## 3. Prediction — MODIS-based bloom forecasting

The goal is a **risk trajectory**, not a claim to foresee blooms. It is a rule-based expert system built from known bloom drivers, and it must be presented that way.

### Signals, all obtainable from MODIS + Sentinel-2 + open climate data

| Signal | Source | Why it matters |
|--------|--------|----------------|
| Chlorophyll anomaly (z-score) | Sentinel-2 / MODIS | Current state |
| 7- and 14-day rate of change | MODIS time series | A rising trend precedes visible bloom |
| Acceleration (2nd derivative) | MODIS time series | Distinguishes steady elevation from rapid growth |
| Sea surface temperature + SST anomaly | MODIS SST | Warm water favours dinoflagellate growth |
| Seasonal climatology position | MODIS 2002–present | Whether the calendar is in a historically bloom-prone window |
| Recent rainfall / runoff proxy | Open precipitation data | Nutrient loading from Chao Phraya, Tha Chin, Mae Klong, Bang Pakong |

### Risk escalation logic

Combine into a small number of explicit, human-readable rules — for example:

```
elevated   ← anomaly z ≥ 1.5
watch      ← anomaly z ≥ 1.5  AND  14-day trend rising
warning    ← anomaly z ≥ 2.0  AND  rising trend  AND  SST above seasonal normal
```

Every rule must be visible in config, not buried in code. If a judge asks why a cell is red, the answer should be a readable sentence, not a model weight.

### Honest limits of the prediction layer

- Published ML forecasting has reached ~96% accuracy predicting bloom onset up to 8 days ahead. **A rule-based system should not be expected to match that**, and must not be described as if it does.
- With only 14 validation events, forecast lead time cannot be meaningfully quantified. Report what was observed, not a performance rate.
- A rising chlorophyll anomaly has other causes — sediment plumes after heavy rain being the most common in the upper Gulf. False alarms are expected and should be stated.

---

## 4. Threshold calibration — the one place the 14 events are used

Thresholds are the only tunable part of the system, and calibrating them is the closest thing to "training" that remains.

**Method:**
1. For each of the 14 events, pull the satellite indices for that date and location.
2. Sweep the threshold across its plausible range.
3. At each value, count how many of the 14 events would have been flagged.
4. Sample non-event dates at the same locations to estimate the false-alarm rate.
5. Choose an operating point and **state explicitly why** — for an early-warning system, missing a bloom costs more than a false alarm, so bias toward sensitivity.

**Reporting rule — this matters more than the threshold itself.** Report per-event, never as a percentage. With n=14, one miss swings a percentage by 7 points, so a headline figure implies precision the sample size cannot support.

Good: *"Of 14 documented events, the system flagged 10. The four missed events were all narrative reports without recorded cell density; the July 2018 super-bloom (>1,500,000 cells/L) was flagged at the highest severity."*

Bad: *"Recall: 71.4%."*

Publish the full 14-row table — event, date, location, whether flagged, index value at the time.

---

## 5. Validation design

The rule protecting the whole project:

> **The data used to calibrate thresholds must never also serve as the evidence that thresholds work.**

- Ground truth is the 14 events, sourced from researchers counting cells in water — independent of any satellite product.
- With n=14, hold-out splitting is not viable. Use **leave-one-out**: calibrate on 13, test on the 1 left out, repeat 14 times. Report which events were caught under this stricter protocol.
- Never generate labels from a satellite threshold and then validate against the same threshold family.

### Secondary validation

The Florida/Gulf-of-Mexico data (836K rows with real cell counts) can validate that the indices behave correctly in general — a sanity check that the physics is implemented right. It says nothing about Gulf of Thailand performance and must be reported separately.

---

## 6. Build phases

**Phase 1 — indices.** Implement NDCI, 2BDA, 3BDA, B2/B3 discrimination over the upper Gulf. Verify against a known-bloom date visually before trusting any number.

**Phase 2 — climatology.** Build the MODIS 2002–present per-location, per-day-of-year baseline. Convert index readings to z-scores.

**Phase 3 — event matching.** For each of the 14 events, extract satellite readings at that date/location. Flag events whose location is too vague for a reliable pixel match — do not force a coordinate the source does not support.

**Phase 4 — threshold calibration.** Sweep, leave-one-out, choose an operating point, produce the 14-row table.

**Phase 5 — prediction layer.** Trend, acceleration, SST, seasonality, rainfall proxy. Implement the escalation rules in config.

**Phase 6 — reporting.** Index comparison, the 14-row table, false-alarm estimate, limitations.

---

## 7. Deliverables

```
detection/
├── src/
│   ├── indices.py           # NDCI, 2BDA, 3BDA, B2/B3 discrimination
│   ├── climatology.py       # MODIS baseline, z-score conversion
│   ├── thresholds.py        # calibration sweep + leave-one-out
│   ├── prediction.py        # trend, SST, seasonality, escalation rules
│   └── config.yaml          # every threshold and rule, human-readable
└── reports/
    ├── event_table.md       # the 14-row per-event result table
    ├── threshold_sweep.png  # sensitivity vs false-alarm trade-off
    └── index_comparison.md  # NDCI vs 2BDA vs 3BDA on the 14 events

data/validation/              # top-level, not under detection/ — see data/validation/README.md
├── events.csv                # canonical, the only file other agents read
└── thailand/                 # citation archive, not read by any agent
    ├── REPORT_THAILAND.md    # source-search summary
    ├── burapha_literature/   # Luang-on et al. (2023) — primary source, 10 events
    ├── seafdec_literature/   # SEAFDEC (2017) + Sudara (1984) — 3 events
    └── moac_bulletin/        # 2018 MOAC bulletin — 1 event
```

---

## 8. Limitations to write down before anyone asks

- **Detection floor.** Blooms smaller than the pixel are missed; at MODIS resolution, detection has been reported to require roughly 13% areal fraction within a pixel. Sentinel-2's 10 m resolution improves this but does not remove it.
- **Turbid water.** Indices designed for open ocean degrade near river mouths — precisely where upper-Gulf blooms occur. This is why 3BDA is carried alongside NDCI.
- **Clouds.** Optical sensors cannot see through cloud. Monsoon months have blind periods, and the system cannot detect what it cannot observe.
- **Surface only.** Satellite signal comes from the first few metres. Subsurface blooms are invisible.
- **Validation sample size.** Fourteen events, most without precise coordinates. Results are indicative, not statistically robust.
- **Prediction is rule-based.** It reflects known bloom drivers, not a validated forecast model, and no lead-time accuracy is claimed.
- **Confounders.** Sediment plumes after heavy rainfall can raise indices without a bloom present.
- **Geographic scope.** Calibrated for the upper Gulf of Thailand only.