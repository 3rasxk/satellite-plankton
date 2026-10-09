"""
`INDEX_METADATA` and the band tables beside `INDEX_FUNCTIONS` in
`src/indices.py` -- the static description `/methods` serves.

Pure: no GEE, no network. What is pinned:
  * one metadata entry per registered index, same keys, same order;
  * each displayed formula, evaluated as plain arithmetic on band values,
    gives exactly what the registered function returns -- so a formula
    shown on the Methods page cannot drift from the code that computes it;
  * each entry lists exactly the bands its formula uses, and the function
    needs no other band;
  * roles agree with `config.yaml`'s `indices` block and with the function
    docstrings (2BDA tied to NDCI, B2/B3 exploratory, not a classifier);
  * every centre wavelength and native resolution is one already stated in
    this module's docstrings -- none is supplied from elsewhere.
"""

import ast
import operator
import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import indices  # noqa: E402
from src.indices import (  # noqa: E402
    BAND_NATIVE_RESOLUTION_M,
    BAND_WAVELENGTHS_NM,
    INDEX_FUNCTIONS,
    INDEX_METADATA,
    INDEX_ROLES,
)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "src" / "config.yaml"
_FIELDS = {"name", "formula", "bands", "role", "note"}
_SENTINEL2_BANDS = ("B2", "B3", "B4", "B5", "B6")

# Band sets with no zero denominator: the worked-example set /methods uses,
# an open-water-like set, a bright turbid set, and one with B5 < B4.
_BAND_SETS = (
    {"B2": 800, "B3": 900, "B4": 600, "B5": 700, "B6": 650},
    {"B2": 412.0, "B3": 385.5, "B4": 231.25, "B5": 198.0, "B6": 140.75},
    {"B2": 1040, "B3": 1660, "B4": 1500, "B5": 1550, "B6": 1210},
    {"B2": 3, "B3": 7, "B4": 11, "B5": 5, "B6": 2},
)

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _evaluate(formula: str, bands: dict) -> float:
    """The displayed formula as plain arithmetic: + - * /, numbers and band names only."""

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            return float(bands[node.id])
        raise AssertionError(f"formula {formula!r} uses unsupported syntax {ast.dump(node)}")

    return walk(ast.parse(formula, mode="eval"))


def _formula_bands(formula: str) -> set[str]:
    return {node.id for node in ast.walk(ast.parse(formula, mode="eval")) if isinstance(node, ast.Name)}


def _config_indices() -> dict:
    with open(_CONFIG_PATH) as handle:
        return yaml.safe_load(handle)["indices"]


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------


def test_metadata_has_one_entry_per_registered_index_in_the_same_order():
    assert list(INDEX_METADATA) == list(INDEX_FUNCTIONS)


@pytest.mark.parametrize("key", list(INDEX_FUNCTIONS))
def test_every_entry_has_exactly_the_documented_fields(key):
    entry = INDEX_METADATA[key]
    assert set(entry) == _FIELDS
    for field in ("name", "formula", "role", "note"):
        assert isinstance(entry[field], str) and entry[field].strip()
    assert entry["role"] in INDEX_ROLES


# --------------------------------------------------------------------------
# Formula strings reflect what the functions compute
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bands", _BAND_SETS)
@pytest.mark.parametrize("key", list(INDEX_FUNCTIONS))
def test_displayed_formula_evaluates_to_the_function_result(key, bands):
    shown = _evaluate(INDEX_METADATA[key]["formula"], bands)
    computed = INDEX_FUNCTIONS[key](bands)
    assert computed == pytest.approx(shown, rel=1e-12, abs=0.0)


def test_worked_example_matches_hand_arithmetic():
    bands = _BAND_SETS[0]
    assert INDEX_FUNCTIONS["ndci"](bands) == (700 - 600) / (700 + 600)
    assert INDEX_FUNCTIONS["2bda"](bands) == 700 / 600
    assert INDEX_FUNCTIONS["3bda"](bands) == (1 / 600 - 1 / 700) * 650
    assert INDEX_FUNCTIONS["b2_b3_ratio"](bands) == 800 / 900


@pytest.mark.parametrize("key", list(INDEX_FUNCTIONS))
def test_bands_field_lists_exactly_the_formula_bands_and_the_function_needs_no_other(key):
    entry = INDEX_METADATA[key]
    assert len(entry["bands"]) == len(set(entry["bands"]))
    assert set(entry["bands"]) == _formula_bands(entry["formula"])
    only_these = {band: _BAND_SETS[1][band] for band in entry["bands"]}
    assert INDEX_FUNCTIONS[key](only_these) == INDEX_FUNCTIONS[key](_BAND_SETS[1])


@pytest.mark.parametrize("key", ["ndci", "2bda", "3bda"])
def test_formula_is_the_one_written_in_the_function_docstring(key):
    assert INDEX_METADATA[key]["formula"] in INDEX_FUNCTIONS[key].__doc__


@pytest.mark.parametrize("key", list(INDEX_FUNCTIONS))
def test_name_is_the_one_in_the_function_docstring(key):
    assert INDEX_METADATA[key]["name"] in INDEX_FUNCTIONS[key].__doc__


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


def test_primary_role_is_the_configured_primary_index_only():
    config = _config_indices()
    primary = [key for key, entry in INDEX_METADATA.items() if entry["role"] == "primary"]
    assert primary == [config["primary"]] == ["ndci"]


def test_2bda_is_derived_and_says_it_is_not_an_independent_signal():
    entry = INDEX_METADATA["2bda"]
    assert entry["role"] == "derived"
    assert [key for key, e in INDEX_METADATA.items() if e["role"] == "derived"] == ["2bda"]
    phrase = "must not be treated as an independent confirming signal"
    assert phrase in entry["note"]
    # The note says what the code's own docstring says, not something new.
    assert phrase in " ".join(INDEX_FUNCTIONS["2bda"].__doc__.split())
    assert "NDCI" in entry["note"]


def test_derived_relation_stated_in_the_note_holds():
    # NDCI = (r - 1) / (r + 1) with r = 2BDA, exactly as the note states.
    for bands in _BAND_SETS:
        r = INDEX_FUNCTIONS["2bda"](bands)
        assert INDEX_FUNCTIONS["ndci"](bands) == pytest.approx((r - 1) / (r + 1), rel=1e-12)


def test_b2_b3_is_exploratory_and_not_a_species_classifier():
    config = _config_indices()
    entry = INDEX_METADATA["b2_b3_ratio"]
    assert entry["role"] == "exploratory"
    assert config["secondary_discrimination"] == "b2_b3_ratio"
    assert [key for key, e in INDEX_METADATA.items() if e["role"] == "exploratory"] == ["b2_b3_ratio"]
    assert "not" in entry["note"] and "species classifier" in entry["note"]
    assert "species classifier" in INDEX_FUNCTIONS["b2_b3_ratio"].__doc__


def test_comparison_role_is_a_configured_comparison_index_that_no_decision_uses():
    config = _config_indices()
    comparison = [key for key, e in INDEX_METADATA.items() if e["role"] == "comparison"]
    assert comparison == ["3bda"]
    for key in comparison:
        assert key in config["compare"] and key != config["primary"]


# --------------------------------------------------------------------------
# Band tables: only values this module's docstrings already state
# --------------------------------------------------------------------------


def _docstrings() -> str:
    """The module's and the index functions' docstrings only -- not comments,
    not INDEX_METADATA's notes, which would make the check circular."""
    docs = [indices.__doc__, *(fn.__doc__ for fn in INDEX_FUNCTIONS.values())]
    return " ".join(" ".join(doc.split()) for doc in docs)


@pytest.mark.parametrize("band,nm", sorted(BAND_WAVELENGTHS_NM.items()))
def test_every_wavelength_is_stated_next_to_its_band_in_the_module_docstrings(band, nm):
    assert re.search(rf"\b{band}\W{{1,3}}{nm} nm\b", _docstrings()), (band, nm)


def test_no_wavelength_is_given_for_a_band_the_module_does_not_document():
    assert set(BAND_WAVELENGTHS_NM) <= set(_SENTINEL2_BANDS)
    # B2/B3 centre wavelengths are stated nowhere in this module, LIMITATIONS.md
    # or docs/DETECTION_PLAN.md, so they are omitted rather than supplied.
    assert "B2" not in BAND_WAVELENGTHS_NM and "B3" not in BAND_WAVELENGTHS_NM


def test_native_resolutions_are_the_ones_the_module_docstring_states():
    match = re.search(r"Resolution: (\d+) m \(([B\d/]+)\) / (\d+) m \(([B\d/]+)\)", indices.__doc__)
    assert match, "module docstring no longer states the band resolutions"
    stated = {}
    for metres, bands in ((match.group(1), match.group(2)), (match.group(3), match.group(4))):
        for band in bands.split("/"):
            stated[band] = int(metres)
    assert BAND_NATIVE_RESOLUTION_M == stated


def test_every_index_band_has_a_native_resolution():
    for entry in INDEX_METADATA.values():
        assert set(entry["bands"]) <= set(BAND_NATIVE_RESOLUTION_M)
