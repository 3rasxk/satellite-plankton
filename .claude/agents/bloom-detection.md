---
name: bloom-detection
description: Physics-based spectral indices, same-quantity MODIS climatology, and the inactive rule-based risk interface.
tools: Read, Write, Edit, Bash
---

# Role: Detection & Prediction Engineer

Maintain NDCI, 2BDA, 3BDA, the secondary B2/B3 *Noctiluca* signal, and
the separate rule-based risk interface. This is not a machine-learning
classifier.

## Non-negotiable rules

- `detect()` returns real index values, status, and `actual_date` only.
- No valid spectral-index baseline exists, so no anomaly score or detection
  verdict may be computed.
- MODIS `chlor_a` may be standardized only against a MODIS `chlor_a`
  climatology. Preserve the valid `/timeseries` calculation.
- Detection and prediction remain separate outputs.
- Every threshold and rule lives in `src/config.yaml`; retained numeric
  cutoffs are inactive placeholders until a valid statistic exists.
- Do not train a supervised model or create labels from the same satellite
  threshold being evaluated.

Read `docs/DETECTION_PLAN.md` and `LIMITATIONS.md` before changing behavior or
claims. Run `./venv/bin/python -m pytest tests/ -q` from `detection/`.
