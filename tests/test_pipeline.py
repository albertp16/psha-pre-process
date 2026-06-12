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


# ── Step 1b: Mw alignment for the seismic moment (vault Day 16 mirror) ──

def test_homogenize_to_mw_priority_and_relations():
    mw_est, src = pl.homogenize_to_mw(
        mw=[np.nan, 7.2], ms=[6.0, 6.5], mb=[5.5, 5.0], fallback=[5.9, 7.2])
    # Ms 6.0 -> 6.09 (Lamessa p. 5, Scordilis 2006 Eq. 8)
    assert round(float(mw_est[0]), 2) == 6.09
    assert src[0] == "ms2mw"
    # reported Mw preferred over Ms/mb (BBS p. 69)
    assert mw_est[1] == 7.2
    assert src[1] == "mw"


def test_homogenize_to_mw_mb_relation_and_fallback():
    mw_est, src = pl.homogenize_to_mw(mb=[5.0, np.nan], fallback=[5.2, 4.6])
    # mb 5.0 -> 5.28 (Lamessa p. 5, Scordilis 2006 Eq. 1)
    assert round(float(mw_est[0]), 2) == 5.28
    assert src.tolist() == ["mb2mw", "raw"]
    assert mw_est[1] == 4.6


def test_homogenize_to_mw_range_gating_protects_largest_events():
    # Ms 8.3 is far outside Scordilis Eq. 8 validity (3.0-6.1): the event
    # must keep its reported value, not be extrapolated down to 7.63.
    mw_est, src = pl.homogenize_to_mw(ms=[8.3, 6.0], fallback=[8.3, 6.0])
    assert mw_est[0] == 8.3
    assert src[0] == "raw"
    assert round(float(mw_est[1]), 2) == 6.09     # in range: converted
    # explicit extrapolation only on request
    mw_est, src = pl.homogenize_to_mw(ms=[8.3], fallback=[8.3],
                                      respect_ranges=False)
    assert round(float(mw_est[0]), 2) == 7.63
    assert src[0] == "ms2mw"


def test_seismic_moment_matches_hanks_kanamori():
    # HK Eq. 7 example: Mw 7.0 -> 3.55e26 dyne-cm = 3.55e19 N·m
    assert pl.seismic_moment_nm(7.0) == pytest.approx(3.55e19, rel=0.01)


def test_magnitude_distribution_report_table():
    # Project-report Table 2.1: 15 / 70 / 604 / 1480 events -> 2169 total,
    # percentages 0.69 / 3.23 / 27.85 / 68.23 (sum 100.00).
    mags = [7.2] * 15 + [6.3] * 70 + [5.4] * 604 + [4.5] * 1480
    rows, n_total, n_below = pl.magnitude_distribution(mags)
    assert (n_total, n_below) == (2169, 0)
    assert [r[0] for r in rows] == [">= 7.0", "6.0 to 6.9",
                                    "5.0 to 5.9", "4.0 to 4.9"]
    assert [r[1] for r in rows] == [15, 70, 604, 1480]
    assert [r[2] for r in rows] == [0.69, 3.23, 27.85, 68.23]
    assert sum(r[2] for r in rows) == pytest.approx(100.0, abs=0.05)


def test_magnitude_distribution_edges_below_min_and_nan():
    # Left-closed bins, inclusive open top bin, NaN dropped, sub-m_min
    # events excluded from the table but counted in n_below.
    rows, n_total, n_below = pl.magnitude_distribution(
        [3.9, 4.0, 4.95, 5.0, 6.999, 7.0, np.nan])
    assert (n_total, n_below) == (5, 1)
    by = {label: n for label, n, _ in rows}
    assert by["4.0 to 4.9"] == 2          # 4.0 inclusive; 4.95 < 5.0
    assert by["5.0 to 5.9"] == 1
    assert by["6.0 to 6.9"] == 1          # 6.999 stays below the top bin
    assert by[">= 7.0"] == 1              # 7.0 lands in the open bin
