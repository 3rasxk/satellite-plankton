# detection

Physics-based bloom index and rule engine. No ML.

## Setup

```bash
cd detection
/opt/homebrew/bin/python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r ../data-pipeline/requirements.txt
earthengine authenticate
```

`EE_PROJECT_ID` is read from `detection/.env`, falling back to
`data-pipeline/.env`. Both files are gitignored.

## Modules

- `src/indices.py` computes NDCI, 2BDA, 3BDA, and an exploratory B2/B3
  context ratio. None is a validated species classifier; NDCI and 2BDA are
  algebraic transforms of the same B5/B4 ratio, not independent evidence.
- `src/climatology.py` builds a MODIS `chlor_a` climatology, valid only for
  comparison with `chlor_a`.
- `src/prediction.py` returns Sentinel-2 index values, status, and the actual
  scene date. It does not compute an anomaly score or detection verdict.
- `src/signal_anomaly.py` defines a pure, guarded robust-z contract for a
  future compatible Sentinel-2 baseline. It is not called by production code.
- `src/config.yaml` retains inactive threshold/rule shapes for a future valid
  statistic; every `calibrated_*` value remains null and risk output is gated
  off.
- `src/_data_pipeline.py` is the namespaced bridge to `data-pipeline/src`.

Run the suite with `./venv/bin/python -m pytest tests/ -q`.
