/**
 * Payloads for the /map tests, trimmed from the live API (backend with
 * BASELINE_MODE=test, run 6 and the older run 1, 2026-10-10): the raster,
 * TEST anomaly pins, NDCI pins of a run without visible bands, and one cell
 * with its TEST anomaly. Lists are shortened; every field kept is verbatim.
 */
export const RASTER = {
  "disclaimer": "Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be visible. TEST baseline mode: a Sentinel-2 NDCI reading, at a monitoring site or at a raster cell, may be compared with that same location's own earlier record for the same season. Any resulting anomaly is provisional and uncalibrated, has never been checked against recorded bloom events, and is a statistical statement only — not a bloom detection, a species identification, a risk level or a forecast. Index values alone establish neither bloom presence nor absence.",
  "run_id": 6,
  "status": "ok",
  "date_used": "2026-10-09",
  "scale_m": 200,
  "cell_count": 235290,
  "scene_count": 32,
  "oldest_scene_date": "2026-09-29",
  "newest_scene_date": "2026-10-07",
  "scene_dates": [
    {
      "date": "2026-10-07",
      "cells": 182486,
      "share": 0.7755790726337711
    },
    {
      "date": "2026-09-29",
      "cells": 36755,
      "share": 0.15621148370096477
    },
    {
      "date": "2026-10-02",
      "cells": 16049,
      "share": 0.06820944366526414
    }
  ],
  "source_metadata": {
    "scene_ids": [
      "20260927T033541_20260927T034657_T47PQR",
      "20260927T033541_20260927T034657_T47PPR",
      "20260927T033541_20260927T034657_T47PNR"
    ],
    "acquisition_dates": [
      "2026-09-29",
      "2026-10-02",
      "2026-10-07"
    ]
  },
  "completed_at": "2026-10-09T13:05:04.669994+00:00",
  "coverage": {
    "measured_fraction": 0.642290001011268,
    "measured_pixels": 209594,
    "polygon_pixels": 326323
  },
  "bounds": [
    [
      12.503567845000363,
      99.91242253062555
    ],
    [
      13.615681814999999,
      101.02812976061746
    ]
  ],
  "legend": {
    "value": {
      "domain": [
        -0.05,
        0.15
      ],
      "swatches": [
        {
          "value": -0.05,
          "hex": "#0a1929"
        },
        {
          "value": -0.04130434782608696,
          "hex": "#102c40"
        },
        {
          "value": -0.03260869565217392,
          "hex": "#173f56"
        }
      ],
      "meaning": "index reading at this cell -- a display ramp, not a risk score: no valid spectral-index baseline exists, so nothing here classifies a cell"
    }
  },
  "overlay_url": "/raster-scan/overlay.png?run_id=6",
  "true_color_url": "/raster-scan/true-color.png?run_id=6",
  "stale_run_id": null,
  "reason": null,
  "latest_scene": {
    "acquisition_date": "2026-10-07",
    "decision": "passed",
    "cloud_fraction": 0.40571297411298207,
    "threshold_cloud_fraction": 0.5,
    "min_water_pixels": 1000,
    "reason": null,
    "used_in_run_id": 6,
    "assessed_at": "2026-10-09T13:04:47.527276+00:00",
    "settled": true,
    "used_in_served_run": true,
    "reassessed_after_use": false
  },
  "last_used_scene_date": "2026-10-07",
  "poll": {
    "last_poll_started_at": "2026-10-10T13:54:58.847144+00:00",
    "last_poll_ok_at": "2026-10-10T13:54:58.847144+00:00",
    "last_error": null,
    "last_error_at": null,
    "last_error_kind": null
  }
}

export const HIGHLIGHTS_ANOMALY = {
  "disclaimer": "Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be visible. TEST baseline mode: a Sentinel-2 NDCI reading, at a monitoring site or at a raster cell, may be compared with that same location's own earlier record for the same season. Any resulting anomaly is provisional and uncalibrated, has never been checked against recorded bloom events, and is a statistical statement only — not a bloom detection, a species identification, a risk level or a forecast. Index values alone establish neither bloom presence nor absence.",
  "run_id": 6,
  "mode": "anomaly",
  "metric": "robust_z",
  "ranking": "descending robust z against this location's own TEST seasonal baseline; not a risk level",
  "n_requested": 5,
  "min_separation_m": 3000,
  "cohort_size": 209594,
  "pins": [
    {
      "rank": 1,
      "cell_lat": 13.337287023322537,
      "cell_lng": 100.21335815052146,
      "pixel_centre_lat": 13.338102480000089,
      "pixel_centre_lng": 100.21335805562336,
      "index_values": {
        "ndci": 0.65398770570755,
        "bda2": 4.780141830444336,
        "bda3": 1.710598349571228,
        "b2_b3": 0.9086294174194336
      },
      "percentile": 99.99951967876115,
      "metric_value": 14.338169744761082,
      "date_ms": 1791345282024,
      "acquired_date": "2026-10-07",
      "acquired_at": "2026-10-07T03:54:42.024000Z",
      "edge_of_no_data": false,
      "risk_tier": null,
      "visible_bands_dn": {
        "red": 141.0,
        "green": 197.0,
        "blue": 179.0
      },
      "robust_z": 14.338169744761082,
      "median_ndci": 0.039851732552051544,
      "mad": 0.02888995222747326,
      "n_dates": 50,
      "anomaly_level": "high"
    },
    {
      "rank": 2,
      "cell_lat": 13.308540934230711,
      "cell_lng": 100.21515478108971,
      "pixel_centre_lat": 13.309356400000098,
      "pixel_centre_lng": 100.21515468562336,
      "index_values": {
        "ndci": 0.5779816508293152,
        "bda2": 3.7391304969787598,
        "bda3": 1.2467138767242432,
        "b2_b3": 0.9321267008781433
      },
      "percentile": 99.9644562283255,
      "metric_value": 11.243527362459584,
      "date_ms": 1791345282024,
      "acquired_date": "2026-10-07",
      "acquired_at": "2026-10-07T03:54:42.024000Z",
      "edge_of_no_data": false,
      "risk_tier": null,
      "visible_bands_dn": {
        "red": 161.0,
        "green": 221.0,
        "blue": 206.0
      },
      "robust_z": 11.243527362459584,
      "median_ndci": 0.03770197555422783,
      "mad": 0.03241097182035446,
      "n_dates": 49,
      "anomaly_level": "high"
    },
    {
      "rank": 3,
      "cell_lat": 13.331897131617819,
      "cell_lng": 100.2798334815463,
      "pixel_centre_lat": 13.332712590000092,
      "pixel_centre_lng": 100.27983336562289,
      "index_values": {
        "ndci": 0.5462753772735596,
        "bda2": 3.4079601764678955,
        "bda3": 1.1178560256958008,
        "b2_b3": 0.7785977721214294
      },
      "percentile": 99.91210121329145,
      "metric_value": 9.779920058622452,
      "date_ms": 1791345282024,
      "acquired_date": "2026-10-07",
      "acquired_at": "2026-10-07T03:54:42.024000Z",
      "edge_of_no_data": false,
      "risk_tier": null,
      "visible_bands_dn": {
        "red": 201.0,
        "green": 271.0,
        "blue": 211.0
      },
      "robust_z": 9.779920058622452,
      "median_ndci": 0.04334365203976631,
      "mad": 0.0346856415271759,
      "n_dates": 55,
      "anomaly_level": "high"
    }
  ],
  "reason": null,
  "baseline": {
    "mode": "test",
    "valid": true,
    "kind": "test",
    "version": "TEST-20261009-9fc9a022",
    "history_start": "2017-12-13",
    "history_end": "2026-10-07",
    "season_rule": "calendar-month window, target month +/- 1 (cyclic)",
    "level_b": {
      "season_key": "m10+-1",
      "months": [
        9,
        10,
        11
      ],
      "history_end": "2026-09-23",
      "min_independent_dates": 30,
      "max_observation_age_days": 14
    }
  },
  "excluded_degenerate": 90,
  "excluded_low_signal": 671,
  "quality_note": null,
  "counts": {
    "measured": 209594,
    "assessable": 208194,
    "no_baseline": 0,
    "insufficient_dates": 639,
    "zero_mad": 0,
    "not_after_history": 0,
    "too_old": 0,
    "invalid": 90,
    "low_signal": 671,
    "watch": 17022,
    "high": 6056,
    "flagged_share": 0.11084853550054276
  }
}

export const HIGHLIGHTS_NDCI = {
  "disclaimer": "Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be visible. TEST baseline mode: a Sentinel-2 NDCI reading, at a monitoring site or at a raster cell, may be compared with that same location's own earlier record for the same season. Any resulting anomaly is provisional and uncalibrated, has never been checked against recorded bloom events, and is a statistical statement only — not a bloom detection, a species identification, a risk level or a forecast. Index values alone establish neither bloom presence nor absence.",
  "run_id": 1,
  "mode": "ndci",
  "metric": "ndci",
  "ranking": "descending value within this run; not a risk level",
  "n_requested": 5,
  "min_separation_m": 3000,
  "cohort_size": 83857,
  "pins": [
    {
      "rank": 1,
      "cell_lat": 13.531323124692353,
      "cell_lng": 100.22952782563561,
      "pixel_centre_lat": 13.532138520000025,
      "pixel_centre_lng": 100.22982887999771,
      "index_values": {
        "ndci": 0.5876288414001465,
        "bda2": 3.8499999046325684,
        "bda3": 7.289610385894775,
        "b2_b3": 0.5072815418243408
      },
      "percentile": 99.99880749370953,
      "metric_value": 0.5876288414001465,
      "date_ms": 1788753278167,
      "acquired_date": "2026-09-07",
      "acquired_at": "2026-09-07T03:54:38.167000Z",
      "edge_of_no_data": true,
      "risk_tier": null,
      "visible_bands_dn": null
    },
    {
      "rank": 2,
      "cell_lat": 13.155827335930393,
      "cell_lng": 100.06423781335762,
      "pixel_centre_lat": 13.15664285000015,
      "pixel_centre_lng": 100.06453891999891,
      "index_values": {
        "ndci": 0.5783783793449402,
        "bda2": 3.7435896396636963,
        "bda3": 6.193211078643799,
        "b2_b3": 0.47637051343917847
      },
      "percentile": 99.99761498741906,
      "metric_value": 0.5783783793449402,
      "date_ms": 1788753278167,
      "acquired_date": "2026-09-07",
      "acquired_at": "2026-09-07T03:54:38.167000Z",
      "edge_of_no_data": true,
      "risk_tier": null,
      "visible_bands_dn": null
    },
    {
      "rank": 3,
      "cell_lat": 13.191759947295173,
      "cell_lng": 100.01033889631046,
      "pixel_centre_lat": 13.192575450000138,
      "pixel_centre_lng": 100.0106400199993,
      "index_values": {
        "ndci": 0.564251184463501,
        "bda2": 3.5898003578186035,
        "bda3": 5.382753849029541,
        "b2_b3": 0.48899754881858826
      },
      "percentile": 99.99403746854765,
      "metric_value": 0.564251184463501,
      "date_ms": 1788753280920,
      "acquired_date": "2026-09-07",
      "acquired_at": "2026-09-07T03:54:40.920000Z",
      "edge_of_no_data": true,
      "risk_tier": null,
      "visible_bands_dn": null
    }
  ],
  "reason": null,
  "baseline": null,
  "excluded_degenerate": 0,
  "excluded_low_signal": null,
  "quality_note": "this run's stored cells carry no visible bands (true_red/true_green/true_blue), so the low-signal screen could not run: pins are not screened for near-black pixels, whose NDCI is unreliable"
}

export const PIXEL_TEST = {
  "disclaimer": "Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be visible. TEST baseline mode: a Sentinel-2 NDCI reading, at a monitoring site or at a raster cell, may be compared with that same location's own earlier record for the same season. Any resulting anomaly is provisional and uncalibrated, has never been checked against recorded bloom events, and is a statistical statement only — not a bloom detection, a species identification, a risk level or a forecast. Index values alone establish neither bloom presence nor absence.",
  "state": "reading",
  "meaning": "index readings at this cell, from the acquisition named by this cell's own date -- a measurement, not a score: no valid spectral-index baseline exists, so nothing here classifies the water",
  "run_id": 6,
  "date_used": "2026-10-09",
  "scale_m": 200,
  "query_lat": 12.69,
  "query_lng": 100.355,
  "cell_lat": 12.688703388188241,
  "cell_lng": 100.35529196541235,
  "pixel_centre_lat": 12.689519050000303,
  "pixel_centre_lng": 100.35529182562234,
  "pixel_row": 515,
  "pixel_col": 246,
  "index_values": {
    "ndci": 0.09756097197532654,
    "bda2": 1.2162162065505981,
    "bda3": 0.20860861241817474,
    "b2_b3": 0.9599999785423279
  },
  "unreadable_bands": [],
  "date_ms": 1791345282024,
  "acquired_date": "2026-10-07",
  "acquired_at": "2026-10-07T03:54:42.024000Z",
  "anomaly": {
    "robust_z": 1.4231799800760923,
    "median_ndci": 0.03986135125160217,
    "mad": 0.027345705777406693,
    "n_dates": 45,
    "level": "normal",
    "reason": null,
    "visible_bands_dn": {
      "red": 444.0,
      "green": 425.0,
      "blue": 408.0
    },
    "baseline_version": "TEST-20261009-9fc9a022",
    "season_key": "m10+-1"
  }
}

