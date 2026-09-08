"""Clicking a point on the raster and getting that pixel's real readings.

Real blobs on a tmp_path root, real PNGs, real DB rows (isolated SQLite,
via the `client` fixture). No GEE anywhere: every cell here is written by
the test, and one test cuts the bridge's Earth Engine entry points and
`urlopen` out from under the endpoint to prove a click never reaches for
either.

What these tests are actually defending. A click has to answer for the
pixel the viewer is pointing at, with the number that is on disk, and it
has to keep saying "not measured" where the picture says so:

    the pixel found      -- the one whose colour is at that position, not
                            its neighbour: an off-by-one is invisible,
                            because both cells are plausible readings
    the value returned   -- the stored bytes, not a rounded or
                            re-derived copy
    "not measured"       -- decided by the DATE band, never by an index
                            value of 0.0, which is a real reading
    the three states     -- reading / unmeasured water / outside the study
                            area stay as distinct in words as in colour

If any of those slipped, the failure would be silent: a plausible number
would appear next to a coordinate, and nothing on the map would look
wrong. So the assertions below compare against the arrays that were
stored and the pixels that were painted, never against a recomputation of
what they ought to be.

THE REFERENCE RULE (stated at the top of test_raster_scan_render.py)
applies here and every comparison below names its reference and whether
it is exhaustive. They are all EXHAUSTIVE by construction: the stored
arrays and the rendered RGBA array enumerate their own contents -- there
is no continuous function being sampled anywhere in this file, so no
assertion here can fail merely because a reference was short.
"""

from __future__ import annotations

import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import delete

from src import _detection as bridge
from src.db import SessionLocal
from src.db_models import RasterScanRun
from src.raster_scan import pixel, render, storage

# Real Sentinel-2 acquisition times over the upper Gulf, as in the storage
# and render suites -- an inspected raster is a real raster.
OLD_MS = 1787628600000  # 2026-08-25T03:30:00Z
NEW_MS = 1788492600000  # 2026-09-04T03:30:00Z

DATE_BAND = bridge.RASTER_DATE_BAND
INDEX_BANDS = bridge.RASTER_INDEX_BANDS

# The grid spacing a 200 m Earth Engine read actually has, in degrees.
STEP_DEG = 200 / render.METRES_PER_DEGREE

# The same small rectangle inside the real study area the render suite
# uses. Small so a whole overlay is a few hundred pixels and a test can
# walk every one of them; real coordinates so nothing depends on a
# fictional geometry.
TEST_POLYGON: tuple[tuple[float, float], ...] = (
    (12.9500, 100.0000),
    (13.0000, 100.0000),
    (13.0000, 100.0500),
    (12.9500, 100.0500),
)

# Inside TEST_POLYGON and inside the real study polygon, but outside the
# lattice below -- water the scan did not measure.
UNMEASURED_LAT, UNMEASURED_LNG = 12.9600, 100.0400

# Far outside the study area (Andaman side of the peninsula).
OUTSIDE_LAT, OUTSIDE_LNG = 9.0000, 98.0000


@pytest.fixture(autouse=True)
def empty_raster_runs(client):
    """One session-wide SQLite file backs the whole suite, so each test
    starts from an empty raster_scan_runs table."""
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()
    yield


def lattice(
    lat_range=(12.9550, 12.9950),
    lng_range=(100.0050, 100.0250),
    sweep=(-0.04, 0.14),
    date_ms=NEW_MS,
):
    """Measured cells on the real 200 m grid, in a blob's returned shape.

    Covers part of TEST_POLYGON on purpose: what is left over is the
    unmeasured water these tests are about. Every index band gets its own
    spread of values rather than one repeated constant, so a lookup that
    returned the wrong cell -- or the right cell's wrong band -- shows up
    as a wrong number instead of coincidentally matching.
    """
    lats = np.arange(lat_range[0], lat_range[1], STEP_DEG)
    lngs = np.arange(lng_range[0], lng_range[1], STEP_DEG)
    lat_grid, lng_grid = np.meshgrid(lats, lngs, indexing="ij")
    lat = lat_grid.ravel().astype(np.float64)
    lng = lng_grid.ravel().astype(np.float64)
    count = lat.size
    return {
        "lat": lat,
        "lng": lng,
        "ndci": np.linspace(sweep[0], sweep[1], count).astype(np.float32),
        "bda2": np.linspace(0.9, 1.7, count).astype(np.float32),
        "bda3": np.linspace(0.1, 0.6, count).astype(np.float32),
        "b2_b3": np.linspace(0.6, 1.1, count).astype(np.float32),
        DATE_BAND: np.full(count, date_ms, dtype=np.int64),
    }


def overlay_grid(cells):
    """The grid these cells' overlay is drawn on, over TEST_POLYGON."""
    return render.build_grid(cells["lat"], cells["lng"], 200, TEST_POLYGON)


def stored_run(db, cells, root, **fields):
    """A committed run row whose blob really is on disk, under its own id
    -- so the overlay lands in the same directory as the cells it was
    drawn from, exactly as a real scan leaves it."""
    run = RasterScanRun(
        started_at=fields.pop("started_at", datetime.now(timezone.utc)),
        completed_at=fields.pop("completed_at", datetime.now(timezone.utc)),
        status="ok",
        date_used="2026-09-07",
        scale_m=200,
        retention_days=30,
        cell_count=int(cells["lat"].size),
        **fields,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    written = storage.write_cells(run.id, cells, root=root)
    run.blob_path = written["path"]
    run.blob_bytes = written["bytes"]
    db.commit()
    return run


def rendered_run(db, cells, root):
    """A run with its cells on disk AND its overlay rendered from them, so
    a pixel query answers against the same grid the picture was drawn on
    -- which is the point of reading the bounds back off the row."""
    run = stored_run(db, cells, root)
    render.render_and_store(db, run, root=root)
    db.refresh(run)
    return run


# --------------------------------------------------------------------------
# Property 1 -- the inverse transform lands in the cell that was painted.
#
# An off-by-one here is the failure mode the whole piece has to rule out:
# the neighbouring cell is also a plausible reading, so a wrong answer
# looks exactly like a right one.
# --------------------------------------------------------------------------


def test_every_stored_cell_is_found_at_its_own_coordinate():
    """Round trip, cell by cell, over the WHOLE blob.

    Reference: `grid.cell_indices()` applied to every stored cell -- the
    very call `render_overlay` makes to decide which pixel each cell
    paints. EXHAUSTIVE: it is the forward transform itself evaluated on
    every cell in the raster, not a sample of it and not a restatement of
    what it ought to compute.
    """
    cells = lattice()
    grid = overlay_grid(cells)
    rows, cols = grid.cell_indices(cells["lat"], cells["lng"])

    mismatched = []
    for i in range(cells["lat"].size):
        located = grid.locate(float(cells["lat"][i]), float(cells["lng"][i]))
        if located != (int(rows[i]), int(cols[i])):
            mismatched.append((i, located, (int(rows[i]), int(cols[i]))))

    assert cells["lat"].size > 200, "a round-trip test over a handful of cells proves little"
    assert not mismatched, (
        f"{len(mismatched)} of {cells['lat'].size} cells were located in a pixel other "
        f"than the one they were painted in, e.g. {mismatched[:3]} (cell index, "
        "located (row, col), painted (row, col))"
    )


def test_the_located_pixel_is_the_one_wearing_that_cells_colour():
    """The inverse transform is checked against the PICTURE, not against
    the transform that produced it.

    Reference: the rendered RGBA array itself. EXHAUSTIVE -- every pixel
    of it exists and is inspected directly; nothing is sampled.
    """
    cells = lattice()
    overlay = render.render_overlay(cells, band="ndci", scale_m=200, polygon=TEST_POLYGON)
    expected_rgb = render.ramp_rgb(cells["ndci"].astype(np.float64), overlay.domain)

    for i in range(cells["lat"].size):
        row, col = overlay.grid.locate(float(cells["lat"][i]), float(cells["lng"][i]))
        painted = overlay.rgba[row, col]
        assert painted[3] == render.VALUE_ALPHA, (
            f"cell {i} at {cells['lat'][i]}, {cells['lng'][i]} located pixel "
            f"({row}, {col}), which the overlay draws as unmeasured (alpha "
            f"{painted[3]}) -- the lookup landed off the painted cell"
        )
        assert tuple(painted[:3]) == tuple(expected_rgb[i]), (
            f"cell {i} located pixel ({row}, {col}), which is painted "
            f"{tuple(int(c) for c in painted[:3])} -- the colour of a different "
            f"cell's reading, not this cell's {float(cells['ndci'][i])}"
        )


def test_a_click_anywhere_inside_a_drawn_square_returns_that_square_s_cell():
    """A cell is drawn as a filled square; every point of that square must
    answer with the same single observation, including its corners.

    Reference: the stored arrays. EXHAUSTIVE over the four corners and the
    centre of every cell's square -- the offsets that a floor()/clip
    boundary error would break.
    """
    cells = lattice()
    grid = overlay_grid(cells)
    inset_lat = grid.pixel_deg_lat * 0.49
    inset_lng = grid.pixel_deg_lng * 0.49

    for i in range(cells["lat"].size):
        row, col = grid.locate(float(cells["lat"][i]), float(cells["lng"][i]))
        centre_lat = grid.north - (row + 0.5) * grid.pixel_deg_lat
        centre_lng = grid.west + (col + 0.5) * grid.pixel_deg_lng
        for d_lat in (-inset_lat, 0.0, inset_lat):
            for d_lng in (-inset_lng, 0.0, inset_lng):
                found = pixel.inspect_cell(
                    cells, centre_lat + d_lat, centre_lng + d_lng, grid, TEST_POLYGON
                )
                assert found["state"] == pixel.STATE_READING
                assert (found["pixel_row"], found["pixel_col"]) == (row, col)
                assert found["cell_lat"] == float(cells["lat"][i])
                assert found["cell_lng"] == float(cells["lng"][i])


def test_a_click_off_the_image_is_not_clipped_onto_the_nearest_edge_cell():
    """`cell_indices` clips, because its input belongs to the raster. A
    click does not belong to the raster, and clipping one would answer a
    query about the open sea with the edge cell's reading."""
    cells = lattice()
    grid = overlay_grid(cells)

    assert grid.locate(OUTSIDE_LAT, OUTSIDE_LNG) is None
    found = pixel.inspect_cell(cells, OUTSIDE_LAT, OUTSIDE_LNG, grid, TEST_POLYGON)
    assert found["state"] == pixel.STATE_OUTSIDE
    assert found["index_values"] is None
    assert found["pixel_row"] is None and found["pixel_col"] is None


# --------------------------------------------------------------------------
# Property 2 -- what is returned is what is stored, byte for byte.
# --------------------------------------------------------------------------


def test_every_cell_reports_the_stored_value_exactly_not_a_rounded_copy():
    """Equality, not approximate equality, on every band of every cell.

    Reference: the stored arrays themselves. EXHAUSTIVE -- the blob is the
    complete set of what this raster holds, and each cell is compared with
    its own entry, so there is nothing to sample and nothing to round.

    `==` is deliberate: `float(np.float32(x))` is exact (every float32 is
    a float64), so a widening cast passes and any rounding, re-scaling or
    re-interpolation on the way out fails.
    """
    cells = lattice()
    grid = overlay_grid(cells)

    for i in range(cells["lat"].size):
        found = pixel.inspect_cell(
            cells, float(cells["lat"][i]), float(cells["lng"][i]), grid, TEST_POLYGON
        )
        assert found["state"] == pixel.STATE_READING
        for band in INDEX_BANDS:
            assert found["index_values"][band] == float(cells[band][i]), (
                f"cell {i} band {band}: returned {found['index_values'][band]!r}, "
                f"stored {float(cells[band][i])!r}"
            )
        assert found["date_ms"] == int(cells[DATE_BAND][i])


def test_the_acquisition_date_survives_as_an_exact_integer():
    """Epoch ms is ~1.79e12 and float32 carries about 7 significant
    digits, so a float32 round trip moves a timestamp by up to ~65 s --
    still a plausible date, no longer the scene's own. The returned value
    must equal the stored integer exactly, and the test proves it is
    sensitive to that by showing the float32 round trip does NOT."""
    cells = lattice(date_ms=NEW_MS)
    grid = overlay_grid(cells)
    found = pixel.inspect_cell(
        cells, float(cells["lat"][0]), float(cells["lng"][0]), grid, TEST_POLYGON
    )

    assert float(np.float32(NEW_MS)) != NEW_MS, (
        "float32 now represents this timestamp exactly, so this test can no longer "
        "tell a narrowed date from an exact one -- pick a timestamp it cannot hold"
    )
    assert found["date_ms"] == NEW_MS
    assert isinstance(found["date_ms"], int)
    assert found["acquired_date"] == "2026-09-04"
    assert found["acquired_at"] == "2026-09-04T03:30:00Z"


def test_each_cell_reports_its_own_date_not_the_rasters():
    """One raster routinely mixes acquisitions -- the composite is
    most-recent-wins per pixel. A click must return the date of the scene
    that supplied THAT cell, never a single date for the picture.

    Reference: the stored date array. EXHAUSTIVE -- every cell checked
    against its own entry.
    """
    cells = lattice()
    # Half the raster from an older pass, as a real mosaic looks.
    cells[DATE_BAND] = np.where(
        np.arange(cells["lat"].size) % 2 == 0, OLD_MS, NEW_MS
    ).astype(np.int64)
    grid = overlay_grid(cells)

    seen = set()
    for i in range(cells["lat"].size):
        found = pixel.inspect_cell(
            cells, float(cells["lat"][i]), float(cells["lng"][i]), grid, TEST_POLYGON
        )
        assert found["date_ms"] == int(cells[DATE_BAND][i])
        seen.add(found["acquired_date"])
    assert seen == {"2026-08-25", "2026-09-04"}, (
        f"the raster carries two acquisition dates but clicks reported {sorted(seen)}"
    )


def test_a_non_finite_reading_is_returned_as_null_not_clamped_to_the_scale():
    """An index is a ratio and a zero-reflectance pixel can produce inf or
    NaN. There is no honest number for "the arithmetic did not produce a
    number", and putting it at either end of the scale would invent a
    reading, so the band comes back null and is named."""
    cells = lattice()
    cells["ndci"] = cells["ndci"].copy()
    cells["ndci"][3] = np.nan
    cells["bda2"] = cells["bda2"].copy()
    cells["bda2"][3] = np.inf
    grid = overlay_grid(cells)

    found = pixel.inspect_cell(
        cells, float(cells["lat"][3]), float(cells["lng"][3]), grid, TEST_POLYGON
    )
    assert found["state"] == pixel.STATE_READING
    assert found["index_values"]["ndci"] is None
    assert found["index_values"]["bda2"] is None
    assert sorted(found["unreadable_bands"]) == ["bda2", "ndci"]
    # The bands that DID produce a number are still reported.
    assert found["index_values"]["bda3"] == float(cells["bda3"][3])


# --------------------------------------------------------------------------
# Property 3 -- "not measured" is decided by the DATE band, never by an
# index value of 0.0. This pair of tests is the point of the property: one
# shows the mask is not read as a reading, the other shows a real 0.0
# still is.
# --------------------------------------------------------------------------


def test_a_masked_cell_is_reported_unmeasured_even_though_its_ndci_is_zero():
    """GEE's NPY export writes 0 into every band of a masked pixel. If
    anything here tested an index for 0 instead of the date, this cell
    would be reported as a measured NDCI of 0.0 -- "we looked and saw
    little chlorophyll" about water nobody could see."""
    cells = lattice()
    for band in INDEX_BANDS:
        cells[band] = cells[band].copy()
        cells[band][7] = 0.0
    cells[DATE_BAND] = cells[DATE_BAND].copy()
    cells[DATE_BAND][7] = 0  # 1970-01-01 -- 45 years before the mission
    grid = overlay_grid(cells)

    found = pixel.inspect_cell(
        cells, float(cells["lat"][7]), float(cells["lng"][7]), grid, TEST_POLYGON
    )
    assert found["state"] == pixel.STATE_NOT_MEASURED, (
        "a masked cell was reported as a reading -- the validity test is looking at "
        "an index value, not at the date band"
    )
    assert found["index_values"] is None
    assert found["date_ms"] is None
    assert "not a low reading" in found["meaning"].lower()


def test_a_genuine_reading_of_exactly_zero_is_still_a_reading():
    """The control for the test above, and the reason the date band has to
    be the discriminator: 0.0 is an ordinary NDCI -- water with equal
    reflectance in B4 and B5 -- and dropping it would throw away real
    measurements while still reporting the mask's own 0.0."""
    cells = lattice()
    cells["ndci"] = cells["ndci"].copy()
    cells["ndci"][7] = 0.0  # real value, real date
    grid = overlay_grid(cells)

    found = pixel.inspect_cell(
        cells, float(cells["lat"][7]), float(cells["lng"][7]), grid, TEST_POLYGON
    )
    assert found["state"] == pixel.STATE_READING
    assert found["index_values"]["ndci"] == 0.0
    assert found["date_ms"] == NEW_MS


def test_the_validity_rule_is_the_data_pipelines_own_not_a_backend_copy(monkeypatch):
    """`date_ms > 0` is defined once, in the module that filters the
    raster on the way in. Cutting that function makes the lookup fail --
    which is what proves the backend is not carrying its own copy that
    could drift out of step with it."""
    cells = lattice()
    grid = overlay_grid(cells)

    # And it agrees with the rule as stated: the date decides, not a value.
    assert bool(bridge.valid_cell_mask(np.array([NEW_MS], dtype=np.int64))[0])
    assert not bool(bridge.valid_cell_mask(np.array([0], dtype=np.int64))[0])

    def refuse(*args, **kwargs):
        raise AssertionError("the backend must use data-pipeline's own validity rule")

    monkeypatch.setattr(bridge, "valid_cell_mask", refuse)
    with pytest.raises(AssertionError):
        pixel.inspect_cell(
            cells, float(cells["lat"][0]), float(cells["lng"][0]), grid, TEST_POLYGON
        )


# --------------------------------------------------------------------------
# Property 4 -- land / outside / unmeasured stay as distinct in words as
# they are in colour, and no more distinct than the data can support.
# --------------------------------------------------------------------------


def test_every_pixel_of_the_overlay_reports_the_state_its_alpha_shows():
    """The whole picture, pixel by pixel, cross-checked against the words.

    Reference: the rendered RGBA array. EXHAUSTIVE -- every pixel in the
    overlay is inspected, none sampled. Alpha alone says which state a
    pixel is drawn in (`render.py`: 0 outside, 255 a reading, between the
    two unmeasured), so this asserts the API and the image never disagree
    about what a viewer is looking at.
    """
    cells = lattice()
    overlay = render.render_overlay(cells, band="ndci", scale_m=200, polygon=TEST_POLYGON)
    grid = overlay.grid
    lats, lngs = grid.pixel_centres()

    expected_for_alpha = {
        render.VALUE_ALPHA: pixel.STATE_READING,
        0: pixel.STATE_OUTSIDE,
    }
    counts = {pixel.STATE_READING: 0, pixel.STATE_NOT_MEASURED: 0, pixel.STATE_OUTSIDE: 0}
    for row in range(grid.rows):
        for col in range(grid.cols):
            alpha = int(overlay.rgba[row, col, 3])
            found = pixel.inspect_cell(
                cells, float(lats[row]), float(lngs[col]), grid, TEST_POLYGON
            )
            expected = expected_for_alpha.get(alpha, pixel.STATE_NOT_MEASURED)
            assert found["state"] == expected, (
                f"pixel ({row}, {col}) is painted with alpha {alpha} "
                f"({expected}) but the lookup called it {found['state']}"
            )
            counts[found["state"]] += 1

    # All three states must actually occur, or the loop above proved
    # nothing about the two it never saw.
    assert all(counts[state] > 0 for state in counts), f"states not all exercised: {counts}"


def test_unmeasured_water_and_outside_the_study_area_are_different_answers():
    """Both are "no reading here", and they are not the same fact: one is
    water the scan tried and failed to see, the other was never looked
    at. The map draws them differently; so does this."""
    cells = lattice()
    grid = overlay_grid(cells)

    unmeasured = pixel.inspect_cell(cells, UNMEASURED_LAT, UNMEASURED_LNG, grid, TEST_POLYGON)
    outside = pixel.inspect_cell(cells, OUTSIDE_LAT, OUTSIDE_LNG, grid, TEST_POLYGON)

    assert unmeasured["state"] == pixel.STATE_NOT_MEASURED
    assert outside["state"] == pixel.STATE_OUTSIDE
    assert unmeasured["state"] != outside["state"]
    assert unmeasured["meaning"] != outside["meaning"]
    for absent in ("index_values", "date_ms", "cell_lat", "cell_lng"):
        assert unmeasured[absent] is None
        assert outside[absent] is None


def test_cloud_land_and_no_pass_are_one_state_and_are_not_guessed_apart():
    """The honest constraint render.py already documents: the stored blob
    keeps only the cells that survived, so it holds no evidence that
    separates cloud from land from no-pass. A lookup must not invent that
    distinction -- three identical absences must produce one identical
    answer."""
    cells = lattice()
    grid = overlay_grid(cells)

    # Three unmeasured coordinates inside the polygon whose real causes
    # would differ on a real scan (coastal land, cloud gap, edge of pass).
    probes = [(12.9600, 100.0400), (12.9700, 100.0350), (12.9880, 100.0450)]
    answers = []
    for lat, lng in probes:
        found = pixel.inspect_cell(cells, lat, lng, grid, TEST_POLYGON)
        assert found["state"] == pixel.STATE_NOT_MEASURED
        answers.append(found["meaning"])

    assert len(set(answers)) == 1, "the lookup distinguished causes it has no evidence for"
    lowered = answers[0].lower()
    for cause in ("cloud", "land", "no scene"):
        assert cause in lowered, f"the one no-data state must name {cause} as a possible cause"


def test_a_reading_that_fell_outside_the_polygon_is_still_reported():
    """A measurement is never erased for being marginally out of bounds --
    the renderer draws it, so the lookup reports it. Order of decision: a
    stored cell wins over the polygon test, exactly as the paint does."""
    cells = lattice(lat_range=(12.9410, 12.9490), lng_range=(100.0050, 100.0150))
    grid = overlay_grid(cells)  # TEST_POLYGON's south edge is 12.95

    inside_polygon = render.points_in_polygon_mask(
        cells["lat"], cells["lng"], TEST_POLYGON
    )
    assert not inside_polygon.any(), "this fixture is meant to sit outside the polygon"

    found = pixel.inspect_cell(
        cells, float(cells["lat"][0]), float(cells["lng"][0]), grid, TEST_POLYGON
    )
    assert found["state"] == pixel.STATE_READING
    assert found["index_values"]["ndci"] == float(cells["ndci"][0])


# --------------------------------------------------------------------------
# The grid a click is resolved on is the grid the picture was drawn on.
# --------------------------------------------------------------------------


def test_the_lookup_uses_the_grid_the_overlay_recorded_not_a_fresh_one(client, tmp_path):
    """Half a pixel of disagreement between the drawn grid and a rebuilt
    one is an off-by-one cell nobody can see is wrong, so the geometry is
    read back from the row the renderer wrote it on."""
    cells = lattice()
    with SessionLocal() as db:
        run = rendered_run(db, cells, tmp_path)
        stored_bounds = run.overlay["bounds"]
        grid = pixel.grid_for_run(run, cells)

    assert grid.rows == stored_bounds["rows"]
    assert grid.cols == stored_bounds["cols"]
    assert grid.north == stored_bounds["north"]
    assert grid.west == stored_bounds["west"]
    assert grid.pixel_deg_lat == stored_bounds["pixel_deg_lat"]


def test_a_run_with_no_recorded_bounds_still_answers_from_its_own_cells(client, tmp_path):
    """A run stored before an overlay existed has no recorded geometry.
    Rebuilding from the cells it does have is worth more than refusing --
    it is the same blob, only the grid is re-derived."""
    cells = lattice()
    with SessionLocal() as db:
        run = stored_run(db, cells, tmp_path)  # no render_and_store, so overlay is None
        found = pixel.inspect_run(run, float(cells["lat"][0]), float(cells["lng"][0]))

    assert found["state"] == pixel.STATE_READING
    assert found["cell_lat"] == float(cells["lat"][0])


def test_an_expired_run_cannot_quote_a_reading_it_no_longer_holds(client, tmp_path):
    """Retention keeps the row and takes the cells. The lookup says so
    rather than answering "not measured", which would blame the satellite
    for something this server lost."""
    cells = lattice()
    with SessionLocal() as db:
        run = stored_run(db, cells, tmp_path)
        blob_path = run.blob_path
        run.blob_path = None
        run.blob_deleted_at = datetime.now(timezone.utc)
        db.commit()

        with pytest.raises(pixel.RasterCellsUnavailableError):
            pixel.inspect_run(run, 12.97, 100.01)

        # Same answer when the row still names a file that is gone.
        run.blob_path = blob_path
        db.commit()
        storage.delete_blob_file(blob_path)
        with pytest.raises(pixel.RasterCellsUnavailableError):
            pixel.inspect_run(run, 12.97, 100.01)


# --------------------------------------------------------------------------
# The endpoint.
# --------------------------------------------------------------------------


def test_the_endpoint_returns_the_stored_cell_under_a_clicked_point(client, tmp_path):
    """End to end, against the same arrays the blob holds.

    Reference: the in-memory cells that were written to disk. EXHAUSTIVE
    for the cell being asked about -- the response is compared with that
    cell's own stored entries, not with a recomputation of them.
    """
    cells = lattice()
    with SessionLocal() as db:
        run = rendered_run(db, cells, tmp_path)
        run_id = run.id

    i = 42
    body = client.get(
        "/raster-scan/pixel",
        params={"lat": float(cells["lat"][i]), "lng": float(cells["lng"][i])},
    ).json()

    assert body["state"] == "reading"
    assert body["run_id"] == run_id
    assert body["cell_lat"] == float(cells["lat"][i])
    assert body["cell_lng"] == float(cells["lng"][i])
    for band in INDEX_BANDS:
        assert body["index_values"][band] == float(cells[band][i])
    assert body["date_ms"] == int(cells[DATE_BAND][i])
    assert body["acquired_date"] == "2026-09-04"
    assert body["scale_m"] == 200
    assert body["disclaimer"]


def test_the_endpoint_answers_from_the_same_run_whose_overlay_is_on_screen(client, tmp_path):
    """A click served from a newer run than the picture would put readings
    on screen that belong to a different image, and nothing about the map
    would show it."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        old = rendered_run(db, lattice(), tmp_path)
        old.started_at = now - timedelta(hours=5)
        db.commit()
        # Newer, cells stored, but never rendered -- /raster-scan keeps
        # serving the older picture, so a click must too.
        newer = stored_run(db, lattice(sweep=(0.30, 0.40)), tmp_path, started_at=now)
        old_id, newer_id = old.id, newer.id

    meta = client.get("/raster-scan").json()
    assert meta["run_id"] == old_id and meta["stale_run_id"] == newer_id

    body = client.get("/raster-scan/pixel", params={"lat": 12.97, "lng": 100.01}).json()
    assert body["run_id"] == old_id, "the click was answered from a run the map is not showing"


def test_a_click_with_no_raster_at_all_is_refused_not_answered_with_zero(client):
    """404, never a body full of nulls that reads as "measured nothing"."""
    response = client.get("/raster-scan/pixel", params={"lat": 12.97, "lng": 100.01})
    assert response.status_code == 404
    assert "No raster overlay" in response.json()["detail"]


def test_a_click_on_a_run_that_lost_its_cells_is_refused(client, tmp_path):
    """The picture is still on disk and still served; the numbers behind
    it are not. Refusing is the only honest answer."""
    cells = lattice()
    with SessionLocal() as db:
        run = rendered_run(db, cells, tmp_path)
        storage.delete_blob_file(run.blob_path)

    assert client.get("/raster-scan").json()["run_id"] is not None
    response = client.get("/raster-scan/pixel", params={"lat": 12.97, "lng": 100.01})
    assert response.status_code == 404
    assert "does not exist" in response.json()["detail"]


def test_the_endpoint_reports_the_three_states_by_name(client, tmp_path):
    cells = lattice()
    with SessionLocal() as db:
        rendered_run(db, cells, tmp_path)

    def state_at(lat, lng):
        return client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng}).json()["state"]

    assert state_at(float(cells["lat"][0]), float(cells["lng"][0])) == "reading"
    assert state_at(UNMEASURED_LAT, UNMEASURED_LNG) == "not_measured"
    assert state_at(OUTSIDE_LAT, OUTSIDE_LNG) == "outside_study_area"


def test_the_unmeasured_probe_really_is_inside_the_real_study_area(client, tmp_path):
    """The precondition the test above depends on, asserted rather than
    assumed: if UNMEASURED_LAT/LNG drifted outside the real polygon, that
    test would keep passing for the wrong reason."""
    assert bridge.check_point_in_study_area(UNMEASURED_LAT, UNMEASURED_LNG)["in_study_area"]
    assert not bridge.check_point_in_study_area(OUTSIDE_LAT, OUTSIDE_LNG)["in_study_area"]


def test_the_response_never_carries_a_risk_level_or_anomaly_score(client, tmp_path):
    """Same truth boundary as every other endpoint: readings only."""
    cells = lattice()
    with SessionLocal() as db:
        rendered_run(db, cells, tmp_path)

    body = client.get(
        "/raster-scan/pixel",
        params={"lat": float(cells["lat"][0]), "lng": float(cells["lng"][0])},
    ).json()
    for forbidden in ("risk_level", "anomaly_z", "spatial_anomaly_z", "threshold_tier",
                      "detected", "severity"):
        assert forbidden not in body, f"{forbidden} must not appear on a raster pixel response"


def test_a_click_never_calls_earth_engine(client, tmp_path, monkeypatch):
    """A click asks what was already measured. With every GEE entry point
    and urlopen cut out from under it, the lookup still answers -- so
    nothing here is quietly re-fetching imagery, which would also mean two
    clicks on one pixel could disagree."""
    cells = lattice()
    with SessionLocal() as db:
        rendered_run(db, cells, tmp_path)

    def refuse(*args, **kwargs):
        raise AssertionError("a pixel lookup must not call Earth Engine or the network")

    for name in ("build_index_composite", "download_composite_arrays",
                 "get_sentinel2_bands", "get_ndci_heatmap", "get_true_color_image",
                 "detect", "risk_level"):
        monkeypatch.setattr(bridge, name, refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    body = client.get(
        "/raster-scan/pixel",
        params={"lat": float(cells["lat"][5]), "lng": float(cells["lng"][5])},
    ).json()
    assert body["state"] == "reading"
    assert body["index_values"]["ndci"] == float(cells["ndci"][5])


def test_an_out_of_range_coordinate_is_rejected_by_the_schema(client, tmp_path):
    with SessionLocal() as db:
        rendered_run(db, lattice(), tmp_path)
    assert client.get("/raster-scan/pixel", params={"lat": 91, "lng": 100.01}).status_code == 422
    assert client.get("/raster-scan/pixel", params={"lat": 12.97}).status_code == 422
