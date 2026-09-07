"""Rendering stored raster cells into a map overlay -- real pixels, real
PNG files on a tmp_path root, real DB rows (isolated SQLite, via the
`client` fixture).

No GEE anywhere, by construction and by assertion: every cell here is
written by the test, and one test cuts the bridge's Earth Engine entry
points and `urlopen` out from under the renderer to prove it never
reaches for either.

What these tests are actually defending. The overlay draws three states,
and the whole point of the piece is that a viewer can tell them apart:

    valued water   -- a reading, on the ramp
    unmeasured water -- inside the study area, nothing usable: grey hatch
    outside        -- nothing drawn at all (alpha 0)

If unmeasured water were ever drawn transparent, or in any colour the
ramp can produce, the map would say "we looked and saw low chlorophyll"
about places nobody looked at. That is this project's cardinal overclaim
in raster form. So the assertions below are on decoded pixel values --
what a viewer's eye actually receives -- never on the shape of the code
that produced them.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import delete

from src import _detection as bridge
from src.db import SessionLocal
from src.db_models import RasterScanRun
from src.raster_scan import render, storage

# Real Sentinel-2 acquisition times over the upper Gulf, as in
# test_raster_scan_storage.py -- a rendered raster is a real raster.
OLD_MS = 1787628600000  # 2026-08-25T03:30:00Z
NEW_MS = 1788492600000  # 2026-09-04T03:30:00Z

DATE_BAND = bridge.RASTER_DATE_BAND

# The grid spacing a 200 m Earth Engine read actually has, in degrees.
STEP_DEG = 200 / render.METRES_PER_DEGREE

# A small rectangle inside the real study area. Small so a whole overlay
# is a few hundred pixels and every assertion can look at all of them;
# real coordinates so nothing here depends on a fictional geometry.
TEST_POLYGON: tuple[tuple[float, float], ...] = (
    (12.9500, 100.0000),
    (13.0000, 100.0000),
    (13.0000, 100.0500),
    (12.9500, 100.0500),
)

LOW = render.NDCI_RAMP_DOMAIN[0]  # the lowest reading the ramp can show
HIGH = render.NDCI_RAMP_DOMAIN[1]


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
    value=0.05,
    sweep=None,
):
    """Measured cells on the real 200 m grid, in a blob's returned shape.

    Covers part of TEST_POLYGON on purpose: what is left over is the
    unmeasured water these tests are about. `sweep=(low, high)` spreads
    readings across that range instead of repeating one value, so a test
    can exercise the whole ramp at once.
    """
    lats = np.arange(lat_range[0], lat_range[1], STEP_DEG)
    lngs = np.arange(lng_range[0], lng_range[1], STEP_DEG)
    lat_grid, lng_grid = np.meshgrid(lats, lngs, indexing="ij")
    lat = lat_grid.ravel().astype(np.float64)
    lng = lng_grid.ravel().astype(np.float64)
    count = lat.size
    values = (
        np.linspace(sweep[0], sweep[1], count).astype(np.float32)
        if sweep is not None
        else np.full(count, value, dtype=np.float32)
    )
    return {
        "lat": lat,
        "lng": lng,
        "ndci": values,
        "bda2": np.full(count, 1.2, dtype=np.float32),
        "bda3": np.full(count, 0.3, dtype=np.float32),
        "b2_b3": np.full(count, 0.8, dtype=np.float32),
        DATE_BAND: np.full(count, NEW_MS, dtype=np.int64),
    }


# --------------------------------------------------------------------------
# THE REFERENCE RULE
#
# Any test here that compares a measured value against a reference set
# must state where that reference came from and whether it is EXHAUSTIVE
# or APPROXIMATE.
#
#   exhaustive  -- every member is present by construction (e.g. the
#                  distinct colours actually in an array). A value
#                  outside it is a real finding.
#   approximate -- built by sampling a continuous function. A value
#                  outside it means EITHER the code is wrong OR the
#                  reference is short. Such a test may report
#                  INCONCLUSIVE. It may never report a defect until the
#                  reference is shown to have saturated.
#
# This is not hypothetical bookkeeping. `ramp_colours(100_001)` returned
# 774 of the ramp's 777 colours, and one assertion below (a rendered
# pixel must BE a ramp colour) fails on any of the 3 it missed -- a
# defect report against correct code. It is the third instance of one
# pattern in this project: the z-score compared an index against another
# quantity's baseline; the water mask read JRC's silence as a positive
# assertion of land; this read a sample as the whole set. Each treated a
# derived or partial reference as authoritative.
# --------------------------------------------------------------------------

RAMP_PALETTE_BASE_SAMPLES = 400_001
_RAMP_PALETTE: dict[str, object] = {}


def _sample_ramp(samples: int) -> set[tuple[int, int, int]]:
    low, high = render.NDCI_RAMP_DOMAIN
    span = high - low
    values = np.linspace(low - span, high + span, samples)
    return {tuple(int(channel) for channel in rgb) for rgb in render.ramp_rgb(values)}


def saturated_ramp_palette(base: int = RAMP_PALETTE_BASE_SAMPLES):
    """The ramp's colours, with evidence that the sample is complete.

    APPROXIMATE by construction: the ramp is a continuous function, so
    its output set can only be sampled. Sampling at base, 2x and 4x and
    requiring the distinct count to stop growing is what turns that into
    a usable reference -- if it is still growing, the set is short and
    nothing may be concluded from a value being outside it.

    Returns (palette, saturated, counts).
    """
    counts = []
    palette: set[tuple[int, int, int]] = set()
    for factor in (1, 2, 4):
        palette = _sample_ramp(base * factor)
        counts.append(len(palette))
    saturated = counts[0] == counts[1] == counts[2]
    return palette, saturated, counts


def ramp_colours() -> set[tuple[int, int, int]]:
    """Every RGB the ramp can produce. APPROXIMATE reference -- see the
    reference rule above. Skips the calling test as INCONCLUSIVE rather
    than letting a short reference masquerade as a finding."""
    if "palette" not in _RAMP_PALETTE:
        palette, saturated, counts = saturated_ramp_palette()
        _RAMP_PALETTE.update(palette=palette, saturated=saturated, counts=counts)
    if not _RAMP_PALETTE["saturated"]:
        pytest.skip(
            "INCONCLUSIVE -- the ramp palette has not saturated "
            f"(counts at 1x/2x/4x: {_RAMP_PALETTE['counts']}). The reference is "
            "incomplete, so nothing can be concluded about the code under test. "
            "Raise RAMP_PALETTE_BASE_SAMPLES."
        )
    return _RAMP_PALETTE["palette"]


def exact_colours(rgba: np.ndarray, mask: np.ndarray | None = None) -> set[tuple[int, int, int]]:
    """The distinct RGBs actually present in an array. EXHAUSTIVE by
    construction -- it enumerates, it does not sample."""
    pixels = rgba[..., :3] if mask is None else rgba[mask][:, :3]
    return {tuple(int(c) for c in px) for px in np.unique(pixels.reshape(-1, 3), axis=0)}


def diagnose(offending, reference, *, source: set | None = None, label: str = "") -> str:
    """A violation message that says which side is broken.

    Reports the offending value, the closest reference entry and its
    distance, and -- decisively -- whether the value is present in the
    source. If it is, the reference is short and the "defect" is an
    artefact of the measurement.
    """
    nearest = min(reference, key=lambda c: sum(abs(a - b) for a, b in zip(c, offending)))
    distance = sum(abs(a - b) for a, b in zip(nearest, offending))
    lines = [
        f"{label}offending value: {offending}",
        f"  nearest reference entry: {nearest} (L1 distance {distance})",
        f"  reference size: {len(reference)}",
    ]
    if source is not None:
        in_source = tuple(offending) in source
        lines.append(f"  present in the source data: {in_source}")
        if in_source:
            lines.append(
                "  => THE REFERENCE IS INCOMPLETE, not the code. This value really "
                "occurs in the source, so the comparison set is short."
            )
    return "\n".join(lines)


def rgb_set(rgba: np.ndarray, mask: np.ndarray) -> set[tuple[int, int, int]]:
    return {tuple(int(channel) for channel in pixel) for pixel in rgba[mask][:, :3]}


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


def state_masks(rendered: render.RenderedOverlay):
    """(inside-polygon, valued) boolean masks for a rendered overlay,
    recomputed from the grid rather than read back out of the renderer --
    so the assertions do not depend on the bookkeeping they are checking."""
    lats, lngs = rendered.grid.pixel_centres()
    inside = render.points_in_polygon_mask(lats[:, None], lngs[None, :], TEST_POLYGON)
    valued = rendered.rgba[..., 3] == render.VALUE_ALPHA
    # `valued` is read off the alpha channel, which is only meaningful
    # because neither hatch tone is allowed to reach 255 -- asserted here
    # rather than assumed, since every other test in this file leans on it.
    for tone in (render.NO_DATA_BASE_RGBA, render.NO_DATA_STRIPE_RGBA):
        assert tone[3] not in (0, render.VALUE_ALPHA)
    return inside, valued


# --------------------------------------------------------------------------
# The three states. These are the tests the piece exists for.
# --------------------------------------------------------------------------


def test_unmeasured_water_never_takes_a_colour_the_ramp_can_produce():
    """THE test. Values sweep the entire ramp; the unmeasured cells must
    still be drawn in something no reading could ever be.

    Asserted against the ramp enumerated at 100,001 points across three
    times its own domain -- the closed set of colours a value can have --
    not against which branch of the renderer ran.
    """
    cells = lattice(sweep=(LOW - 0.1, HIGH + 0.1))
    rendered = render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON)
    inside, valued = state_masks(rendered)

    no_data = inside & ~valued
    assert no_data.sum() > 0, "the fixture must leave some water unmeasured"
    assert not (rgb_set(rendered.rgba, no_data) & ramp_colours())


def test_the_no_data_hatch_is_achromatic_and_the_ramp_never_is():
    """WHY the test above cannot regress by accident: the hatch is grey
    (r == g == b) and no interpolation between the ramp's stops ever is,
    so the two sets are disjoint by construction and not by luck."""
    for tone in (render.NO_DATA_BASE_RGBA, render.NO_DATA_STRIPE_RGBA):
        assert tone[0] == tone[1] == tone[2], f"{tone} is not a neutral grey"

    chromatic = [rgb for rgb in ramp_colours() if rgb[0] == rgb[1] == rgb[2]]
    assert chromatic == [], f"the ramp can produce grey: {chromatic[:5]}"


def test_a_genuine_low_reading_renders_as_the_ramps_low_colour_not_as_the_hatch():
    """A real, low reading is a measurement and must look like one."""
    cells = lattice(value=LOW)
    rendered = render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON)
    _, valued = state_masks(rendered)

    drawn = {tuple(int(channel) for channel in pixel) for pixel in rendered.rgba[valued]}
    lowest_stop = bridge.hex_to_rgb(render.NDCI_RAMP_HEX[0])
    assert drawn == {(*lowest_stop, render.VALUE_ALPHA)}
    assert (*lowest_stop, render.VALUE_ALPHA) not in {
        render.NO_DATA_BASE_RGBA, render.NO_DATA_STRIPE_RGBA
    }


def test_a_low_reading_and_an_unmeasured_cell_are_far_apart_in_colour():
    """The confusion that matters, measured. "We saw very little" and "we
    could not see" sit side by side in the same image here, and must not
    be a near-match a viewer could mistake for gradient noise."""
    cells = lattice(value=LOW)
    rendered = render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON)
    inside, valued = state_masks(rendered)

    low_colour = np.array(bridge.hex_to_rgb(render.NDCI_RAMP_HEX[0]), dtype=float)
    for tone in (render.NO_DATA_BASE_RGBA, render.NO_DATA_STRIPE_RGBA):
        distance = np.linalg.norm(np.array(tone[:3], dtype=float) - low_colour)
        assert distance > 100, f"hatch {tone} is only {distance:.0f} from the low colour"

    # And they genuinely are neighbours in this image, not merely both
    # present somewhere in it.
    boundary = inside & valued
    neighbours = inside & ~valued
    assert boundary.sum() > 0 and neighbours.sum() > 0


def test_everything_outside_the_polygon_is_fully_transparent():
    """Land and open sea beyond the study area: the basemap already says
    what is there, so nothing is drawn over it."""
    cells = lattice()
    rendered = render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON)
    inside, valued = state_masks(rendered)

    outside = ~inside & ~valued
    assert outside.sum() > 0, "the fixture must include area outside the polygon"
    assert np.all(rendered.rgba[outside, 3] == 0)
    assert np.all(rendered.rgba[outside] == np.array(render.OUTSIDE_RGBA, dtype=np.uint8))


def test_unmeasured_water_inside_the_polygon_is_never_transparent():
    """The other half of the same rule: inside the study area, "no
    reading" is drawn, loudly. A transparent hole here would read as a
    measurement of low chlorophyll."""
    cells = lattice()
    rendered = render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON)
    inside, valued = state_masks(rendered)

    no_data_alpha = rendered.rgba[inside & ~valued, 3]
    assert no_data_alpha.size > 0
    assert no_data_alpha.min() >= render.NO_DATA_MIN_ALPHA > 0


def test_every_pixel_is_exactly_one_of_the_three_states():
    """No fourth state, no in-between: an overlay that blended value into
    no-data at the edges would put unclassifiable colours on the map."""
    cells = lattice(sweep=(LOW, HIGH))
    rendered = render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON)

    values = ramp_colours()
    hatch = {render.NO_DATA_BASE_RGBA, render.NO_DATA_STRIPE_RGBA}
    seen = {tuple(int(c) for c in pixel) for pixel in rendered.rgba.reshape(-1, 4)}
    for pixel in seen:
        is_outside = pixel == render.OUTSIDE_RGBA
        is_hatch = pixel in hatch
        is_value = pixel[3] == render.VALUE_ALPHA and pixel[:3] in values
        assert sum((is_outside, is_hatch, is_value)) == 1, f"{pixel} is not one state"


def test_alpha_alone_says_which_state_a_pixel_is_in():
    """The channel that does the separating. 0 outside, 255 measured,
    strictly between for unmeasured -- so "was this measured?" never
    depends on matching an RGB triple against a palette, and a hatch tone
    can never be read as a reading."""
    cells = lattice(sweep=(LOW, HIGH))
    rendered = render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON)
    inside, valued = state_masks(rendered)

    alpha = rendered.rgba[..., 3]
    assert set(np.unique(alpha[~inside & ~valued]).tolist()) == {0}
    assert set(np.unique(alpha[valued]).tolist()) == {render.VALUE_ALPHA}
    no_data_alphas = np.unique(alpha[inside & ~valued]).tolist()
    assert no_data_alphas
    assert all(0 < value < render.VALUE_ALPHA for value in no_data_alphas)
    assert min(no_data_alphas) == render.NO_DATA_MIN_ALPHA
    assert max(no_data_alphas) == render.NO_DATA_MAX_ALPHA


def test_a_non_finite_reading_is_drawn_as_unmeasured_not_as_a_value():
    """An index is a ratio, and a division by a zero-reflectance pixel can
    return inf or NaN with a perfectly good acquisition date attached.
    There is no honest colour for "the arithmetic produced no number", and
    silently pinning it to an end of the ramp would invent a reading."""
    cells = lattice(value=0.05)
    cells["ndci"] = cells["ndci"].copy()
    cells["ndci"][0] = np.nan
    cells["ndci"][1] = np.inf

    rendered = render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON)

    assert rendered.stats["unreadable_cells"] == 2
    grid = rendered.grid
    for position in (0, 1):
        row, col = grid.cell_indices(cells["lat"][position:position + 1],
                                     cells["lng"][position:position + 1])
        pixel = tuple(int(channel) for channel in rendered.rgba[row[0], col[0]])
        assert pixel in {render.NO_DATA_BASE_RGBA, render.NO_DATA_STRIPE_RGBA}
        assert pixel[:3] not in ramp_colours()


# --------------------------------------------------------------------------
# Geometry: where the picture goes, and how big a cell is allowed to look.
# --------------------------------------------------------------------------


def test_the_overlay_always_covers_the_whole_study_polygon():
    """An overlay sized to its cells would shrink on a cloudy day, and the
    water that went missing would leave the image entirely instead of
    being drawn as unmeasured -- the same overclaim by a different route.
    The extent is the polygon, whatever the cells cover."""
    corner_only = lattice(lat_range=(12.9550, 12.9600), lng_range=(100.0050, 100.0100))
    rendered = render.render_overlay(corner_only, scale_m=200, polygon=TEST_POLYGON)
    grid = rendered.grid

    assert grid.south <= min(vertex[0] for vertex in TEST_POLYGON)
    assert grid.north >= max(vertex[0] for vertex in TEST_POLYGON)
    assert grid.west <= min(vertex[1] for vertex in TEST_POLYGON)
    assert grid.east >= max(vertex[1] for vertex in TEST_POLYGON)
    assert grid.leaflet_bounds == [[grid.south, grid.west], [grid.north, grid.east]]
    # Almost none of it was measured, and the picture says so.
    assert rendered.stats["measured_fraction"] < 0.05
    assert rendered.stats["no_data_pixels"] > 10 * rendered.stats["valued_pixels"]


def test_a_cell_lands_in_the_pixel_its_coordinates_name():
    """Placement, checked by inverting it: the one lit pixel's own centre,
    computed back from the returned bounds, is within half a pixel of the
    cell that was stored. A half-pixel error here slides the whole raster
    across the map."""
    one = lattice(lat_range=(12.9700, 12.9705), lng_range=(100.0200, 100.0205), value=HIGH)
    assert one["lat"].size == 1
    rendered = render.render_overlay(one, scale_m=200, polygon=TEST_POLYGON)

    lit = np.argwhere(rendered.rgba[..., 3] == render.VALUE_ALPHA)
    assert lit.shape == (1, 2)
    row, col = lit[0]
    grid = rendered.grid
    pixel_lat = grid.north - (row + 0.5) * grid.pixel_deg_lat
    pixel_lng = grid.west + (col + 0.5) * grid.pixel_deg_lng
    assert abs(pixel_lat - one["lat"][0]) <= grid.pixel_deg_lat / 2
    assert abs(pixel_lng - one["lng"][0]) <= grid.pixel_deg_lng / 2


def test_a_measured_cell_outside_the_polygon_is_still_drawn():
    """A real reading is never erased for landing marginally outside the
    boundary -- the polygon decides where the hatch goes, not which
    measurements are allowed to exist."""
    cells = lattice(lat_range=(12.9550, 12.9600), lng_range=(100.0050, 100.0100))
    cells["lat"] = np.append(cells["lat"], 12.9400)  # just south of the polygon
    cells["lng"] = np.append(cells["lng"], 100.0250)
    cells["ndci"] = np.append(cells["ndci"], np.float32(HIGH))

    rendered = render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON)

    assert rendered.stats["valued_pixels_outside_polygon"] == 1
    row, col = rendered.grid.cell_indices(np.array([12.9400]), np.array([100.0250]))
    assert rendered.rgba[row[0], col[0], 3] == render.VALUE_ALPHA
    assert tuple(int(c) for c in rendered.rgba[row[0], col[0], :3]) in ramp_colours()


def test_scattered_cells_are_never_painted_as_kilometre_wide_blocks():
    """A cell is one nearest-neighbour-sampled native pixel. If the pixel
    size were inferred from the gaps between a handful of surviving cells,
    each would be drawn as a block kilometres across -- confident colour
    over water nobody sampled."""
    sparse = {
        "lat": np.array([12.9600, 12.9800, 12.9900]),
        "lng": np.array([100.0100, 100.0300, 100.0400]),
        "ndci": np.array([0.05, 0.06, 0.07], dtype=np.float32),
    }
    rendered = render.render_overlay(sparse, scale_m=200, polygon=TEST_POLYGON)

    assert rendered.grid.pixel_size_source == "scale_m"
    assert rendered.grid.pixel_deg_lat == pytest.approx(STEP_DEG)
    assert rendered.stats["valued_pixels"] == 3


def test_an_overlay_finer_than_the_pixel_ceiling_is_refused():
    """A mistaken scale must fail with the numbers in the message, not by
    trying to allocate gigabytes."""
    with pytest.raises(render.OverlayTooLargeError, match="ceiling"):
        render.render_overlay(lattice(), scale_m=1, polygon=render.STUDY_AREA_POLYGON_LATLNG)


# --------------------------------------------------------------------------
# Reuse: one ramp, one boundary rule -- no second copy that could drift.
# --------------------------------------------------------------------------


def test_the_vectorised_ramp_matches_data_pipelines_own_scalar_ramp():
    """`ramp_rgb` is a vectorisation of imagery.ndci_value_to_color, not a
    second palette.

    Reference provenance: APPROXIMATE, saturating. Two implementations of
    a continuous function can only be compared at sampled inputs, so
    "they agree" is always "they agree where we looked". This looks at
    the density where the ramp's output set stops growing
    (RAMP_PALETTE_BASE_SAMPLES), which means every colour either can
    produce is exercised, and well past the domain in both directions
    where both must clamp. It was 997 samples, which is agreement over
    0.2% of that -- enough to miss a divergence confined to a few
    adjacent values.
    """
    low, high = render.NDCI_RAMP_DOMAIN
    span = high - low
    values = np.linspace(low - span, high + span, RAMP_PALETTE_BASE_SAMPLES)

    vectorised = render.ramp_rgb(values)
    produced = set()
    for value, colour in zip(values, vectorised):
        as_tuple = tuple(int(c) for c in colour)
        scalar = bridge.ndci_value_to_color(float(value))
        assert as_tuple == scalar, (
            f"vectorised and scalar ramps diverge at NDCI {value!r}: "
            f"{as_tuple} vs {scalar}"
        )
        produced.add(as_tuple)

    # The sample is only meaningful if it covered the whole output set.
    assert produced == ramp_colours(), (
        "the comparison did not exercise every colour the ramp can produce, "
        "so agreement here is weaker than it looks"
    )
    assert render.NDCI_RAMP_HEX == bridge.NDCI_RAMP_HEX
    assert render.NDCI_RAMP_DOMAIN == bridge.NDCI_RAMP_DOMAIN


EDGE_PROBE_OFFSET_DEG = 1e-4  # ~11 m: unambiguously off the line, still hugging it
EDGE_PROBES_PER_EDGE = 200


def _edge_probe_points(polygon):
    """Points just inside and just outside every polygon edge.

    Two implementations of point-in-polygon agree trivially in the open
    interior; they diverge, if at all, next to an edge. A lattice is
    least dense exactly there, so the edges are walked directly and
    probed on both sides along each edge's normal.

    Points nearer the line than EDGE_PROBE_OFFSET_DEG are deliberately
    not probed: neither implementation claims a boundary rule (see
    study_area.point_in_polygon's docstring), so a disagreement on the
    line itself would not be a defect in either.
    """
    probes = []
    count = len(polygon)
    for index in range(count):
        lat_a, lng_a = polygon[index]
        lat_b, lng_b = polygon[(index + 1) % count]
        for step in np.linspace(0.02, 0.98, EDGE_PROBES_PER_EDGE):
            lat = lat_a + (lat_b - lat_a) * step
            lng = lng_a + (lng_b - lng_a) * step
            d_lat, d_lng = lat_b - lat_a, lng_b - lng_a
            length = float(np.hypot(d_lat, d_lng)) or 1.0
            # Unit normal to this edge.
            n_lat, n_lng = -d_lng / length, d_lat / length
            for sign in (1.0, -1.0):
                probes.append((
                    lat + n_lat * EDGE_PROBE_OFFSET_DEG * sign,
                    lng + n_lng * EDGE_PROBE_OFFSET_DEG * sign,
                ))
    return probes


def test_the_polygon_mask_agrees_with_the_study_area_boundary_check():
    """The vectorised ray casting is the same rule data-pipeline's
    `check_point_in_study_area` applies, run on a grid.

    Reference provenance: APPROXIMATE, and unavoidably so -- the plane is
    continuous, so no finite check is exhaustive. What it does cover is
    stated rather than implied:

      - EDGES, densely: 200 points along each of the polygon's edges,
        probed ~11 m either side of the line. This is where two
        point-in-polygon implementations can actually disagree, and it is
        precisely where the previous 41x41 lattice was thinnest -- most
        of its 1,681 points sat in open interior or open exterior, where
        agreement is trivial.
      - INTERIOR and EXTERIOR, coarsely: the original lattice, kept, so a
        gross error away from the edges is still caught.

    Not covered, and not claimed: the boundary line itself, within
    ~11 m. Neither implementation defines a rule there.
    """
    polygon = render.STUDY_AREA_POLYGON_LATLNG

    edge_disagreements = [
        (lat, lng)
        for lat, lng in _edge_probe_points(polygon)
        if bool(render.points_in_polygon_mask(
            np.array([[lat]]), np.array([[lng]]), polygon
        )[0, 0]) != bridge.check_point_in_study_area(lat, lng)["in_study_area"]
    ]
    assert edge_disagreements == [], (
        f"{len(edge_disagreements)} disagreement(s) beside the polygon edge, "
        f"e.g. {edge_disagreements[:3]}"
    )

    lats = np.linspace(12.3, 13.8, 41)
    lngs = np.linspace(99.7, 101.3, 41)
    mask = render.points_in_polygon_mask(lats[:, None], lngs[None, :], polygon)
    lattice_disagreements = [
        (float(lat), float(lng))
        for row, lat in enumerate(lats)
        for col, lng in enumerate(lngs)
        if bool(mask[row, col]) != bridge.check_point_in_study_area(lat, lng)["in_study_area"]
    ]
    assert lattice_disagreements == []
    assert mask.any() and not mask.all()

    # The edge probes are only meaningful if they land on both sides.
    inside = sum(
        bridge.check_point_in_study_area(lat, lng)["in_study_area"]
        for lat, lng in _edge_probe_points(polygon)
    )
    total = len(_edge_probe_points(polygon))
    assert 0 < inside < total, (
        f"edge probes landed {inside}/{total} inside -- they are not straddling "
        "the boundary, so they test nothing"
    )


def test_a_band_with_no_agreed_display_domain_is_refused():
    """Only NDCI has a display domain anyone in this project has chosen.
    Picking a min/max for the others decides which readings look alarming,
    so it is a human's call, and the renderer says so instead of guessing."""
    cells = lattice()
    cells["bda2"] = np.full(cells["lat"].size, 1.2, dtype=np.float32)

    with pytest.raises(render.UnrenderableBandError, match="display domain"):
        render.render_overlay(cells, band="bda2", scale_m=200, polygon=TEST_POLYGON)
    assert render.RENDERED_BANDS == ("ndci",)


# --------------------------------------------------------------------------
# The files, the row, and what retention does to them.
# --------------------------------------------------------------------------


def test_the_written_png_decodes_to_exactly_the_rendered_pixels(tmp_path):
    """The assertions above are about an array; this is the file a browser
    will actually receive. PNG is lossless and keeps its alpha channel, so
    the two must be identical -- a JPEG here would blend hatch grey into
    value colours at every edge and produce pixels that are neither."""
    cells = lattice(sweep=(LOW, HIGH))
    rendered = render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON)

    path = tmp_path / "overlay_ndci.png"
    size = render.write_png(rendered.rgba, path)

    with Image.open(path) as image:
        assert image.mode == "RGBA"
        decoded = np.array(image)
    assert size == path.stat().st_size
    assert np.array_equal(decoded, rendered.rgba)
    # And the three states survived the round trip through the file.
    assert (decoded[..., 3] == 0).any()
    assert np.isin(decoded[..., 3], [render.NO_DATA_BASE_RGBA[3],
                                     render.NO_DATA_STRIPE_RGBA[3]]).any()
    assert (decoded[..., 3] == render.VALUE_ALPHA).any()


def test_the_assets_and_bounds_are_persisted_on_the_run_row(client, tmp_path):
    """A PNG with no bounds is not a map layer. Both are stored on the run
    so a later piece can serve the overlay from the row alone."""
    cells = lattice()

    with SessionLocal() as db:
        run = stored_run(db, cells, tmp_path)
        run_id = run.id

        stored = render.render_and_store(db, run, root=tmp_path)

    with SessionLocal() as db:
        row = db.get(RasterScanRun, run_id)
        overlay = row.overlay
    assert overlay["status"] == "ok"
    asset = overlay["assets"]["ndci"]
    assert Path(asset["path"]).exists()
    assert asset["bytes"] == Path(asset["path"]).stat().st_size
    assert overlay["bounds"]["leaflet_bounds"] == stored["bounds"]["leaflet_bounds"]
    assert len(overlay["bounds"]["leaflet_bounds"]) == 2
    # The legend travels with the paths: whatever draws this must not have
    # to guess what the grey means.
    assert "Not a low reading" in overlay["legend"]["no_data"]["meaning"]
    assert overlay["legend"]["transparent"]["rgba"] == list(render.OUTSIDE_RGBA)
    # The sidecar says the same thing next to the image itself, so the
    # PNG stays placeable if the database is ever rebuilt.
    sidecar = Path(overlay["sidecar_path"])
    assert sidecar.exists() and sidecar.parent == Path(asset["path"]).parent
    # And the overlay sits beside the cells it was drawn from.
    assert sidecar.parent == storage.run_blob_dir(run_id, tmp_path)
    # The sidecar and the row hold the same document, so a rebuilt
    # database does not leave a PNG nobody can place on a map.
    assert json.loads(sidecar.read_text()) == overlay


def test_rendering_reads_the_stored_blob_and_never_calls_earth_engine(
    client, tmp_path, monkeypatch
):
    """An overlay is a picture of what was already measured. With every
    GEE entry point and urlopen cut out from under it, rendering still
    completes -- so nothing here is quietly re-fetching imagery."""
    def refuse(*args, **kwargs):
        raise AssertionError("the renderer must not call Earth Engine or the network")

    for name in ("build_index_composite", "download_composite_arrays",
                 "get_sentinel2_bands", "get_ndci_heatmap", "get_true_color_image"):
        monkeypatch.setattr(bridge, name, refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    with SessionLocal() as db:
        run = stored_run(db, lattice(), tmp_path)

        stored = render.render_and_store(db, run, root=tmp_path)

    assert Path(stored["assets"]["ndci"]["path"]).exists()
    assert stored["assets"]["ndci"]["valued_pixels"] > 0


def test_an_expired_run_cannot_be_rendered_from_a_missing_blob(client, tmp_path):
    """Retention took the cells; the renderer says so rather than
    producing an empty overlay that looks like a real one."""
    with SessionLocal() as db:
        run = RasterScanRun(
            started_at=datetime.now(timezone.utc), status="ok", date_used="2026-09-07",
            scale_m=200, retention_days=30, blob_path=None,
            blob_deleted_at=datetime.now(timezone.utc), summary={"cell_count": 3},
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        with pytest.raises(ValueError, match="no blob to render"):
            render.render_and_store(db, run, root=tmp_path)

        run.blob_path = str(tmp_path / "999" / storage.BLOB_FILENAME)
        with pytest.raises(FileNotFoundError, match="blob_deleted_at"):
            render.render_and_store(db, run, root=tmp_path)


def test_retention_removes_the_overlay_with_the_cells(client, tmp_path):
    """The overlay is drawn from the cells, so it cannot outlive them: an
    image nobody can redraw or check against its source is exactly the
    orphan retention exists to prevent. The run keeps its summary."""
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    cells = lattice()

    with SessionLocal() as db:
        run = stored_run(
            db, cells, tmp_path,
            started_at=now - timedelta(days=40),
            completed_at=now - timedelta(days=40),
            summary={"cell_count": int(cells["lat"].size)},
        )
        run_id = run.id
        overlay = render.render_and_store(db, run, root=tmp_path)
        assets = [Path(path) for path in overlay["files"]]
        assert all(path.exists() for path in assets)

        result = storage.apply_retention(db, now=now, retention_days=30, root=tmp_path)

        assert result["expired"] == [run.id]
        db.refresh(run)
        assert run.overlay is None
        assert run.blob_path is None
        assert run.summary == {"cell_count": int(cells["lat"].size)}
    assert [path for path in assets if path.exists()] == []
    # Nothing of this run is left behind on disk -- the directory goes too.
    assert not storage.run_blob_dir(run_id, tmp_path).exists()


def test_the_frontend_legend_fixture_still_matches_this_renderer():
    """frontend/tests/fixtures/raster_legend.json is generated from
    legend_swatches() and asserted against the legend component. A
    static fixture goes stale silently: change the ramp and the
    frontend test would keep passing against the OLD colours while the
    map painted new ones -- exactly the legend/picture drift the
    swatches exist to prevent. This fails instead, and regenerating the
    fixture is the fix."""
    import json
    from pathlib import Path

    from src.raster_scan import render

    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "frontend" / "tests" / "fixtures" / "raster_legend.json"
    )
    assert fixture_path.exists(), f"legend fixture missing at {fixture_path}"
    fixture = json.loads(fixture_path.read_text())

    assert fixture["ramp_hex"] == list(render.NDCI_RAMP_HEX)
    assert fixture["domain"] == list(render.NDCI_RAMP_DOMAIN)
    assert fixture["no_data_base_rgba"] == list(render.NO_DATA_BASE_RGBA)
    assert fixture["no_data_stripe_rgba"] == list(render.NO_DATA_STRIPE_RGBA)
    assert fixture["swatches"] == render.legend_swatches(render.NDCI_RAMP_DOMAIN), (
        "the legend fixture no longer matches the renderer's ramp -- regenerate it"
    )


# --------------------------------------------------------------------------
# Resampling: the overlay is scaled by the browser, and a blend of the
# grey hatch with a ramp colour would paint unmeasured water in something
# that reads as a reading. `image-rendering: pixelated` selects nearest
# neighbour to prevent that.
#
# Reference: EXHAUSTIVE. Nearest neighbour SELECTS source pixels, so its
# output is necessarily a subset of the source's own distinct colours --
# which are enumerable, finite and exact. No sampling of ramp_rgb() is
# involved or permitted here; that is what made the first version of this
# check report an impossible violation.
# --------------------------------------------------------------------------


def _rendered_overlay_rgba():
    """A real overlay containing all three states."""
    cells = lattice(sweep=(-0.06, 0.16))
    return render.render_overlay(cells, scale_m=200, polygon=TEST_POLYGON).rgba


def test_nearest_neighbour_resampling_cannot_introduce_a_colour(pytestconfig):
    """The guarantee behind image-rendering: pixelated.

    Nearest neighbour cannot invent a colour -- it copies them. So an
    output colour outside the source's own set is not a defect in the
    renderer; it is proof the measurement is broken (the resampler was
    not nearest, or the reference was built wrong). The assertion says
    so, because a previous version of this check blamed the code.
    """
    from PIL import Image

    rgba = _rendered_overlay_rgba()
    source = exact_colours(rgba)
    source_alpha = {int(a) for a in np.unique(rgba[..., 3])}
    image = Image.fromarray(rgba, mode="RGBA")
    width, height = image.size

    for factor in (2, 3, 4, 8):
        if width // factor < 2:
            continue
        small = np.asarray(
            image.resize((width // factor, height // factor), Image.NEAREST)
        )
        produced = exact_colours(small)
        introduced = produced - source
        assert not introduced, (
            "MEASUREMENT IS BROKEN, not the code under test: nearest-neighbour "
            f"resampling at 1/{factor} produced a colour absent from the source. "
            "Selection cannot create values.\n"
            + diagnose(sorted(introduced)[0], source, source=source,
                       label=f"  at 1/{factor}: ")
        )
        stray_alpha = {int(a) for a in np.unique(small[..., 3])} - source_alpha
        assert not stray_alpha, (
            f"nearest resampling at 1/{factor} produced alpha values {stray_alpha} "
            f"absent from the source {sorted(source_alpha)} -- states have blended"
        )


def test_smooth_resampling_does_introduce_colours_so_the_check_is_sensitive():
    """Without this, 'nearest introduced nothing' could be vacuous -- a
    test that cannot fail proves nothing. Bilinear blends neighbours, so
    it must produce colours the source never held."""
    from PIL import Image

    rgba = _rendered_overlay_rgba()
    source = exact_colours(rgba)
    image = Image.fromarray(rgba, mode="RGBA")
    width, height = image.size

    blended = np.asarray(image.resize((width // 4, height // 4), Image.BILINEAR))
    introduced = exact_colours(blended) - source
    assert introduced, (
        "bilinear resampling introduced no new colours, so this check cannot "
        "distinguish blending from selection and the nearest-neighbour result "
        "above is not evidence of anything"
    )


def test_a_short_reference_reports_inconclusive_rather_than_a_defect():
    """The rule itself, exercised: a deliberately truncated reference
    must not let a test claim a defect."""
    palette, saturated, counts = saturated_ramp_palette(base=101)
    assert not saturated, "101 samples cannot have saturated a 777-colour ramp"
    assert counts[0] < counts[-1], f"expected the count to still be growing, got {counts}"

    full, full_saturated, full_counts = saturated_ramp_palette()
    assert full_saturated, f"the configured base no longer saturates: {full_counts}"
    assert palette < full, "the truncated reference should be a strict subset"


def test_the_diagnostic_names_the_reference_when_the_reference_is_short():
    """Failure output has to say which side is broken, or the next
    person debugs the wrong thing -- as happened here."""
    short = {(0, 0, 0), (255, 255, 255)}
    real = (32, 92, 122)
    message = diagnose(real, short, source={real}, label="test: ")
    assert "THE REFERENCE IS INCOMPLETE" in message
    assert "present in the source data: True" in message
    assert str(real) in message

    message_genuine = diagnose(real, short, source=set())
    assert "present in the source data: False" in message_genuine
    assert "THE REFERENCE IS INCOMPLETE" not in message_genuine
