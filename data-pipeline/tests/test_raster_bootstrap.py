"""Pure bootstrap-window coverage; no Earth Engine or network calls."""

from src import raster


def test_bootstrap_windows_page_back_newest_first_without_future_or_overlap():
    windows = list(
        raster.iter_bootstrap_windows(
            "2026-09-06",
            archive_start_date="2026-08-01",
        )
    )

    assert windows == [
        {"target_date": "2026-09-06", "max_scene_age_days": 14,
         "window_start": "2026-08-23", "window_end": "2026-09-07"},
        {"target_date": "2026-08-22", "max_scene_age_days": 14,
         "window_start": "2026-08-08", "window_end": "2026-08-23"},
        {"target_date": "2026-08-07", "max_scene_age_days": 6,
         "window_start": "2026-08-01", "window_end": "2026-08-08"},
    ]


def test_bootstrap_windows_stop_at_the_surface_reflectance_archive_start():
    windows = list(raster.iter_bootstrap_windows("2017-03-28"))
    assert windows == [
        {"target_date": "2017-03-28", "max_scene_age_days": 0,
         "window_start": "2017-03-28", "window_end": "2017-03-29"},
    ]
    assert raster.SENTINEL2_SR_ARCHIVE_START_DATE == "2017-03-28"
