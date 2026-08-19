# CLAUDE.md — Gulf of Thailand Algal Bloom Monitor

> How to use: place this file + the `.claude/agents/` folder at the repo root.
> Open Claude Code (Fable 5) and say: "Read CLAUDE.md and all agent files, then build in Build Order."

## 0. Project (do not deviate)

Software-only early-warning system for harmful algal blooms (green *Noctiluca* / red tide) in the upper Gulf of Thailand, targeting SDG 14. **Physics-based, not machine learning.** Two layers + a web app:

1. **Satellite layer** Sentinel-2 (10 m, current detail) + MODIS (~1 km, 2002–present, climatology baseline) via Google Earth Engine.
2. **Detection & prediction layer** Spectral indices (NDCI / 2BDA / 3BDA) → anomaly z-score against MODIS climatology → rule-based risk escalation. No trained model.
3. **Web dashboard** for viewing/inspection — no LINE, no push. Risk shown as colours on a map.

### Why no ML
Public HAB databases (HAEDAT, FWC, HABSOS, PMN — 836K rows) contain **zero usable Thailand coastal records in the satellite era**. Only 14 documented Thai events were recoverable, and those are the validation set, not training data. Florida *Karenia brevis* does not transfer to green *Noctiluca* (different optical mechanism), and self-labelling from a satellite threshold is circular. See `docs/DETECTION_PLAN.md` §0.

### Truth boundary (mandatory in every output — no overclaiming)
- Detection is at **satellite pixel resolution** (Sentinel-2 ~10 m, MODIS ~1 km) — water colour signatures only, never individual organisms.
- Small or dispersed blooms may be **missed**; state this.
- **Detection and prediction are separate claims.** Detection (is there an anomaly now) is high-confidence standard remote sensing. Prediction (is risk rising) is rule-based and indicative — never presented as a validated forecast.
- Validation uses **14 documented Thai events**. Always report **per-event, never as a percentage** — with n=14, a percentage implies precision the sample cannot support.

## 1. Locked decisions (do not propose alternatives unless the human asks)

| Topic | Decided | Rejected |
|-------|---------|----------|
| Approach | Physics: spectral indices + anomaly z-score + rule-based escalation | ❌ supervised ML / trained classifier |
| Indices | NDCI, 2BDA, 3BDA, B2/B3 *Noctiluca* discrimination — compare, don't assume | |
| Baseline | MODIS `chlor_a` 2002–present climatology, per location per day-of-year | |
| Primary satellite | Sentinel-2 (10 m) via GEE | |
| Secondary satellite | MODIS via GEE — climatology + SST | |
| Ground truth | 14 documented Thai events only | ❌ labels derived from a satellite threshold |
| Validation | Leave-one-out over the 14 events, reported per-event | ❌ 70/30 split on self-generated labels |
| Frontend | React (Vite) + Leaflet/MapLibre | |
| Backend | FastAPI (Python) | |
| Alerting | Colours on the map in the web app | ❌ LINE/email push |

## 2. Agents (full detail in `.claude/agents/<name>.md`)

| Agent | Responsibility (short) |
|-------|------------------------|
| `satellite-data` | Sentinel-2 + MODIS pipeline via GEE; band extraction, cloud masking |
| `bloom-detection` | Indices, climatology z-scores, threshold calibration, rule-based prediction |
| `backend-api` | FastAPI: risk-map / timeseries / detect / summary + scheduler + DB |
| `frontend-dashboard` | React web: map + charts + summary (no LINE) |
| `integration-docs` | Assembly, e2e tests, README, LIMITATIONS.md, overclaim guard |

## 3. Build Order

```
[human: GEE approved + authenticated]
        │
        ▼
satellite-data ──► bloom-detection
                        │
                        ▼
                   backend-api
                        ▼
                 frontend-dashboard
                        ▼
                  integration-docs
```

`bloom-detection` depends on `satellite-data` (it needs real band values and MODIS history), so these run in sequence, not parallel.

## 4. What the human must do (agents cannot — remind the user)

1. **Google Earth Engine** — sign up (free for research, needs approval), authenticate locally. If auth fails with an SSL certificate error, a Python from another toolchain (e.g. PlatformIO) is being used — create a clean virtualenv from the system Python instead.
2. **Confirm the 14 Thai events file** — `data/validation/events.csv`, extracted from Luang-on et al. (2023, *Frontiers in Marine Science* 10:1031901), a SEAFDEC-archived 1984 paper, and a 2018 MOAC bulletin. This set is locked — no further data collection is planned. Verify coordinates where the source gives only a place-name.
3. **Confirm the study area bounding box** (upper Gulf of Thailand) and focus sites (e.g. Chonburi / Bang Saen).
4. **Supabase/DB keys** + hosting account.
5. **Review thresholds and escalation rules** in `detection/src/config.yaml` — accept or change.

## 5. Shared conventions

- Repo: `/data-pipeline` `/detection` `/backend` `/frontend` `/docs`
- Validation dataset lives in `/data/validation/` — see `data/validation/README.md` for the schema. `data/validation/events.csv` is the single file other agents read; `data/validation/thailand/` (source subfolders + `REPORT_THAILAND.md`) is a citation archive only, not read by any agent. **This set is fixed at 14 events — no further data collection is in scope.**
- Config via env vars + `.env.example` only — never commit secrets.
- Every module has a docstring stating data source + limitations.
- Comments/docs may be English; identifiers in English.

## 6. Definition of Done

- [ ] Sentinel-2 + MODIS pipeline pulling real data for the upper Gulf
- [ ] All three indices implemented and compared against the 14 events
- [ ] MODIS climatology built, anomaly z-scores computed
- [ ] Leave-one-out threshold calibration complete, 14-row per-event table published
- [ ] Rule-based prediction layer with every rule readable in config
- [ ] Web: map + click-to-chart + summary page
- [ ] LIMITATIONS.md states the truth boundary; no percentage claims on n=14; no overclaiming
- [ ] README reproducible from scratch