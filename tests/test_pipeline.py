"""Unit tests for psha_preprocess.catalogue.pipeline.

Each correctness check mirrors a defect documented in CODE_REVIEW.md
(A1, A2, A3, A5, B1) and the cited behaviour of
reference/psha_pipeline_reference.py.
"""
import doctest
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from psha_preprocess.catalogue import pipeline as pl

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Doctests are the citation-bearing contract (CLAUDE.md) ──────────

def test_pipeline_doctests():
    results = doctest.testmod(pl, verbose=False)
    assert results.attempted > 0
    assert results.failed == 0


def test_reference_doctests():
    ref_path = REPO_ROOT / "reference" / "psha_pipeline_reference.py"
    spec = importlib.util.spec_from_file_location("psha_pipeline_reference", ref_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    results = doctest.testmod(mod, verbose=False)
    assert results.attempted > 0
    assert results.failed == 0


# ── A1: declustering must never delete a larger later event ────────

def test_decluster_largest_event_survives():
    # M7.5 ten days after a nearby M5.0: the M7.5 is the mainshock,
    # the M5.0 is its foreshock (BBS Sec. 3.3.5, pp. 73, 75).
    t = np.array([0.0, 10.0])
    la = np.array([14.6, 14.6])
    lo = np.array([121.0, 121.0])
    m = np.array([5.0, 7.5])
    is_main = pl.gardner_knopoff_decluster(t, la, lo, m, method="gk")
    assert is_main.tolist() == [False, True]


def test_decluster_independent_events_kept():
    # Far apart in time: both are mainshocks.
    t = np.array([0.0, 5000.0])
    la = np.array([14.6, 14.6])
    lo = np.array([121.0, 121.0])
    m = np.array([6.0, 6.0])
    is_main = pl.gardner_knopoff_decluster(t, la, lo, m, method="gk")
    assert is_main.tolist() == [True, True]


def test_decluster_methods_all_run():
    rng = np.random.default_rng(42)
    n = 200
    t = np.sort(rng.uniform(0, 40000, n))
    la = rng.uniform(5, 20, n)
    lo = rng.uniform(117, 127, n)
    m = rng.uniform(4.5, 7.5, n)
    for method in ("gk", "gr", "uh"):
        is_main = pl.gardner_knopoff_decluster(t, la, lo, m, method=method)
        # the largest event of the catalogue is always a mainshock
        assert is_main[np.argmax(m)]


# ── A2: rates count events only inside their completeness period ───

def test_completeness_rates_excludes_pre_completeness_events():
    ct = [[1960, 4.0], [1920, 6.0]]
    mags = np.array([4.5, 4.5, 6.5])
    years = np.array([1950, 1990, 1930])  # first event pre-completeness
    edges = np.array([4.0, 5.0, 6.0, 7.0])
    r = pl.completeness_rates(mags, years, ct, edges, 2020)
    assert np.allclose(np.round(r, 5), [0.01667, 0.0, 0.01])


def test_completeness_year_lookup():
    ct = [[1960, 4.0], [1920, 6.0]]
    assert pl.completeness_year_for(ct, 4.5) == 1960.0
    assert pl.completeness_year_for(ct, 6.5) == 1920.0
    assert pl.completeness_year_for(ct, 3.0) is None


# ── A5/B-value: Aki MLE recovers a known b on synthetic data ────────

def test_b_value_aki_synthetic():
    rng = np.random.default_rng(7)
    b_true = 1.2
    m = 4.0 + rng.exponential(1.0 / (b_true * np.log(10)), 50000)
    b, db = pl.b_value_aki(m, 4.0)
    assert abs(b - b_true) < 0.03
    assert 0 < db < 0.02


def test_b_value_aki_degenerate_input():
    b, db = pl.b_value_aki(np.array([5.0]), 4.0)
    assert np.isnan(b) and np.isnan(db)


# ── A3: Kijko–Sellevoll Mmax properties (kijko2004.pdf, pp. 1659–60) ─

def test_kijko_sellevoll_above_observed():
    mhat = pl.kijko_sellevoll_mmax(m_obs=7.0, n=300, b=1.0, m_min=4.5)
    assert mhat >= 7.0
    assert round(mhat, 2) == pytest.approx(7.59, abs=0.01)


def test_kijko_sellevoll_increment_shrinks_with_n():
    m1 = pl.kijko_sellevoll_mmax(7.0, 300, 1.0, 4.5)
    m2 = pl.kijko_sellevoll_mmax(7.0, 3000, 1.0, 4.5)
    assert m2 < m1


# ── Step 2: duplicate removal keeps the first of a close pair ───────

def test_remove_duplicates():
    t = np.array([0.0, 10.0, 4000.0])
    la = np.array([14.6, 14.6, 14.6])
    lo = np.array([121.0, 121.0, 121.0])
    m = np.array([5.0, 5.1, 5.0])
    assert pl.remove_duplicates(t, la, lo, m).tolist() == [True, False, True]


# ── Step 1: harmonization converts only the supplied scales ─────────

def test_harmonize_to_mw():
    mags = np.array([5.0, 6.0, 5.5])
    scales = np.array(["Ms", "Mw", "Mb"])
    coeffs = {"Ms": (0.67, 2.07), "Mb": (1.38, -1.79)}
    mw, conv = pl.harmonize_to_mw(mags, scales, coeffs)
    assert np.allclose(np.round(mw, 2), [5.42, 6.0, 5.8])
    assert conv.tolist() == [True, False, True]
