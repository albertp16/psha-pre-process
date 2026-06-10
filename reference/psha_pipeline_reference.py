"""
psha_pipeline_reference.py — suggested reference implementations for psha-pre-process.

Correct-process building blocks for catalogue preparation, in pipeline order:

    1. harmonize_to_mw        (BBS Sec. 3.3.5, Harmonization, p. 69)
    2. remove_duplicates      (BBS Sec. 3.3.5 checklist, p. 68)
    3. gardner_knopoff_decluster  (BBS Sec. 3.3.5, Declustering, pp. 73, 75)
    4. completeness_rates     (BBS Fig. 3.10, p. 78; Completeness Levels pp. 71-72)
    5. b_value_aki            (Lamessa et al., Eq. 21-22, p. 7 of 24)
    6. kijko_sellevoll_mmax   (kijko2004.pdf, Eqs. 6-8, pp. 1659-1660)

Conventions follow the psha-mind vault: standalone NumPy, docstring citation,
runnable doctest per function.  "BBS" = Baker, Bradley & Stafford (2022),
Seismic Hazard and Risk Analysis; printed page = PDF page - 13.

Run tests:  python3 -m doctest psha_pipeline_reference.py -v
"""
import numpy as np


# ── 1. Harmonization ────────────────────────────────────────────────

def harmonize_to_mw(mags, scales, coeffs):
    """Convert mixed-scale magnitudes to moment magnitude Mw.

    Basis: BBS, Sec. 3.3.5 (Harmonization), p. 69 — "seismicity datasets
    commonly need to be converted to moment magnitude ... it is essential
    to have consistency when specifying rates and ground motions."
    Folder example of the workflow: Lamessa et al. (Ethiopia), Methods,
    pp. 4-6 of 24 (linear inter-scale regressions, region-specific).

    NOTE: regression coefficients for the Philippines are NOT in the
    Reference Folder — they must be supplied by the user and cited.
    `coeffs` maps scale name -> (slope, intercept): Mw = slope*M + intercept.
    Scales absent from `coeffs` pass through unchanged and are flagged.

    Returns (mw, converted_mask).

    >>> mags = np.array([5.0, 6.0, 5.5])
    >>> scales = np.array(["Ms", "Mw", "Mb"])
    >>> coeffs = {"Ms": (0.67, 2.07), "Mb": (1.38, -1.79)}  # EXAMPLE ONLY
    >>> mw, conv = harmonize_to_mw(mags, scales, coeffs)
    >>> np.round(mw, 2).tolist()
    [5.42, 6.0, 5.8]
    >>> conv.tolist()
    [True, False, True]
    """
    mags = np.asarray(mags, dtype=float)
    scales = np.asarray(scales)
    mw = mags.copy()
    converted = np.zeros(len(mags), dtype=bool)
    for scale, (a, b) in coeffs.items():
        m = scales == scale
        mw[m] = a * mags[m] + b
        converted[m] = True
    return mw, converted


# ── 2. Duplicate removal ────────────────────────────────────────────

def remove_duplicates(times_s, lats, lons, mags,
                      time_tol_s=60.0, dist_tol_km=50.0, mag_tol=0.5):
    """Keep the first of any pair of events closer than the tolerances.

    Basis: BBS, Sec. 3.3.5 checklist, p. 68 — "Duplicate removal: ensure
    that each event is represented only once."

    `times_s`: event times in seconds (any epoch), assumed sortable.
    Returns boolean keep-mask aligned with the (time-sorted) input order.

    >>> t = np.array([0.0, 10.0, 4000.0])
    >>> la = np.array([14.6, 14.6, 14.6]); lo = np.array([121.0, 121.0, 121.0])
    >>> m = np.array([5.0, 5.1, 5.0])
    >>> remove_duplicates(t, la, lo, m).tolist()
    [True, False, True]
    """
    order = np.argsort(times_s)
    t, la, lo, m = (np.asarray(x, dtype=float)[order]
                    for x in (times_s, lats, lons, mags))
    n = len(t)
    keep = np.ones(n, dtype=bool)
    for i in range(n - 1):
        if not keep[i]:
            continue
        j = i + 1
        while j < n and t[j] - t[i] <= time_tol_s:
            if keep[j] and abs(m[j] - m[i]) <= mag_tol:
                if _haversine_km(la[i], lo[i], la[j], lo[j]) <= dist_tol_km:
                    keep[j] = False
            j += 1
    out = np.ones(n, dtype=bool)
    out[order] = keep
    return out


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance, km (vectorized)."""
    r1, r2 = np.radians(lat1), np.radians(lat2)
    dlat = r2 - r1
    dlon = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(r1) * np.cos(r2) * np.sin(dlon / 2) ** 2
    return 6371.0 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


# ── 3. Declustering (corrected Gardner-Knopoff logic) ───────────────

def gk_windows(mags):
    """Gardner-Knopoff space (km) / time (days) windows.

    Basis for the *concept*: BBS, Sec. 3.3.5, p. 75 — windows are increasing
    functions of the MAINSHOCK magnitude; events inside are associated with
    the mainshock.  The numeric coefficients below match the existing
    web_app.py / OpenQuake-HMTK values; the Gardner & Knopoff (1974) source
    paper is NOT in the Reference Folder — add it before relying on them.

    >>> s, t = gk_windows(np.array([6.0]))
    >>> bool(s[0] > 50) and bool(400 < t[0] < 600)
    True
    """
    m = np.asarray(mags, dtype=float)
    space = 10.0 ** (0.1238 * m + 0.983)
    time_days = np.where(m >= 6.5,
                         10.0 ** (0.032 * m + 2.7389),
                         10.0 ** (0.5409 * m - 0.547))
    return space, time_days


def gardner_knopoff_decluster(times_days, lats, lons, mags, window_fn=gk_windows):
    """Window declustering with the mainshock = largest event of the cluster.

    Fixes the two defects of the current web_app implementation:
      * events are processed largest-magnitude-first, so a later, larger
        event is never deleted as the "aftershock" of a smaller one;
      * foreshocks are removed too (window applied both ways in time).

    Basis: BBS, Sec. 3.3.5, pp. 73, 75 — declustering removes foreshocks
    AND aftershocks; GK windows are defined around the mainshock.

    `times_days`: event time in days (float).  Returns True = mainshock.

    >>> t = np.array([0.0, 10.0, 1500.0])    # M7 ten days after M5, nearby
    >>> la = np.array([14.6, 14.6, 14.6]); lo = np.array([121.0, 121.0, 121.0])
    >>> m = np.array([5.0, 7.0, 5.0])        # M7 window ~918 d: 3rd event clear
    >>> gardner_knopoff_decluster(t, la, lo, m).tolist()
    [False, True, True]
    """
    t = np.asarray(times_days, dtype=float)
    la, lo, m = (np.asarray(x, dtype=float) for x in (lats, lons, mags))
    n = len(t)
    space_w, time_w = window_fn(m)
    is_main = np.ones(n, dtype=bool)
    classified = np.zeros(n, dtype=bool)
    for i in np.argsort(m)[::-1]:           # largest magnitude first
        if classified[i]:
            continue
        classified[i] = True                # i is a mainshock
        in_time = (np.abs(t - t[i]) <= time_w[i]) & ~classified
        if not in_time.any():
            continue
        idx = np.where(in_time)[0]
        d = _haversine_km(la[i], lo[i], la[idx], lo[idx])
        dep = idx[d <= space_w[i]]
        is_main[dep] = False                # fore/aftershocks of i
        classified[dep] = True
    return is_main


# ── 4. Completeness-corrected rates ─────────────────────────────────

def completeness_rates(mags, years, completeness_table, edges, end_year):
    """Annual incremental rates counting events only inside their
    period of completeness.

    Fixes the api_mfd defect: an event is counted ONLY if it occurred on
    or after the completeness year of its magnitude bin, and the count is
    divided by (end_year - completeness_year) for that bin.

    Basis: BBS, Fig. 3.10, p. 78 — rates are obtained from event counts
    "in light of the corresponding period of completeness for each
    magnitude"; Completeness Levels, pp. 71-72.

    `completeness_table`: [[year, mag], ...] meaning complete for M >= mag
    from `year` on.  `edges`: magnitude bin edges (ascending).

    >>> ct = [[1960, 4.0], [1920, 6.0]]
    >>> mags  = np.array([4.5, 4.5, 6.5])
    >>> years = np.array([1950, 1990, 1930])   # first event pre-completeness
    >>> r = completeness_rates(mags, years, ct, np.array([4., 5., 6., 7.]), 2020)
    >>> np.round(r, 5).tolist()
    [0.01667, 0.0, 0.01]
    """
    mags = np.asarray(mags, dtype=float)
    years = np.asarray(years, dtype=float)
    ct = sorted((float(y), float(mg)) for y, mg in completeness_table)
    centers = (edges[:-1] + edges[1:]) / 2.0
    rates = np.zeros(len(centers))
    for i, mc in enumerate(centers):
        cy = None
        for y, mg in sorted(ct, key=lambda p: p[1]):
            if mg <= mc:
                cy = y
        if cy is None:                      # bin below lowest complete level
            continue
        dur = max(end_year - cy, 1.0)
        in_bin = (mags >= edges[i]) & (mags < edges[i + 1]) & (years >= cy)
        rates[i] = in_bin.sum() / dur
    return rates


# ── 5. b-value (Aki MLE) + Shi & Bolt error ─────────────────────────

def b_value_aki(mags, mc, dm=0.0):
    """Maximum-likelihood b-value with optional binning correction.

    Basis: Lamessa et al. (Homogenized earthquake catalog ... Ethiopia),
    Eq. (21), p. 7 of 24:  b = log10(e) / (Mmean - Mc).
    Standard error: Shi & Bolt formula, Eq. (22), same page.
    The dm/2 binning correction (set dm > 0 to apply) is the form used in
    web_app.py; it has NO basis in the Reference Folder — cite Utsu (1965)
    /Bender (1983) and add the source before relying on it.

    Returns (b, delta_b).

    >>> rng = np.random.default_rng(1)
    >>> m = 4.0 + rng.exponential(1.0 / (1.0 * np.log(10)), 20000)
    >>> b, db = b_value_aki(m, 4.0)
    >>> bool(abs(b - 1.0) < 0.03), bool(db < 0.02)
    (True, True)
    """
    m = np.asarray(mags, dtype=float)
    m = m[m >= mc]
    n = len(m)
    if n < 2:
        return np.nan, np.nan
    b = np.log10(np.e) / (m.mean() - (mc - dm / 2.0))
    db = 2.30 * b ** 2 * np.sqrt(((m - m.mean()) ** 2).sum() / (n * (n - 1)))
    return b, db


# ── 6. Maximum magnitude (Kijko-Sellevoll) ──────────────────────────

def _e1(z):
    """Exponential integral E1(z), accurate for all z > 0.

    For z > 1: the Abramowitz & Stegun rational approximation quoted in
    kijko2004.pdf, p. 1660 (a1=2.334733, a2=0.250621, b1=3.330657,
    b2=1.681534).  That approximation is invalid for small arguments, so
    for z <= 1 the defining series E1(z) = -gamma - ln z - sum((-z)^k/(k*k!))
    is used (mathematical identity of the same function Kijko cites to
    Abramowitz & Stegun, 1970).
    """
    z = float(z)
    if z > 1.0:
        a1, a2, b1, b2 = 2.334733, 0.250621, 3.330657, 1.681534
        return ((z ** 2 + a1 * z + a2)
                / (z * (z ** 2 + b1 * z + b2))) * np.exp(-z)
    gamma = 0.5772156649015329
    total, term = 0.0, 1.0
    for k in range(1, 40):
        term *= -z / k
        total += term / k
    return -gamma - np.log(z) - total


def kijko_sellevoll_mmax(m_obs, n, b, m_min, span_max=5.0):
    """Kijko-Sellevoll estimator of mmax for the doubly truncated GR
    distribution.

        mmax = m_obs + [E1(n2) - E1(n1)] / (beta * exp(-n2)) + m_min * exp(-n)
        n1   = n / (1 - exp(-beta * (mmax - m_min)))
        n2   = n1 * exp(-beta * (mmax - m_min)),   beta = b * ln(10)

    Basis: kijko2004.pdf, Eqs. (6)-(8), pp. 1659-1660 (Cramer approximation
    of the generic equation; "the assessment of mmax is obtained by the
    iterative solution of equation (8)").  Always >= m_obs by construction
    (p. 1659: "the integral D is never negative").  Solved here by bisection
    on f(m) = m_obs + delta(m) - m for numerical robustness; per p. 1660,
    when mmax - m_min >= 2 and n >= 100 the non-iterative variant
    (mmax -> m_obs in n1, n2) is an acceptable shortcut.

    >>> mhat = kijko_sellevoll_mmax(m_obs=7.0, n=300, b=1.0, m_min=4.5)
    >>> round(mhat, 2)
    7.59
    >>> # increment shrinks as n grows (more data -> mmax closer to observed)
    >>> bool(kijko_sellevoll_mmax(7.0, 3000, 1.0, 4.5) < mhat)
    True
    """
    beta = b * np.log(10.0)

    def f(mmax):
        span = mmax - m_min
        n1 = n / (1.0 - np.exp(-beta * span))
        n2 = n1 * np.exp(-beta * span)
        delta = (_e1(n2) - _e1(n1)) / (beta * np.exp(-n2)) \
            + m_min * np.exp(-n)
        return m_obs + delta - mmax

    lo, hi = m_obs + 1e-9, m_obs + span_max
    if f(hi) > 0:                # no root below span_max: return upper bound
        return float(hi)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-6:
            break
    return float(0.5 * (lo + hi))


if __name__ == "__main__":
    import doctest
    res = doctest.testmod(verbose=False)
    print(f"doctests: {res.attempted} run, {res.failed} failed")
