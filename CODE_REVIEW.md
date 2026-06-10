# Code Review — psha-pre-process

Reviewed: `web_app.py` (1,120 LOC), `psha_preprocess/catalogue/` (completeness, converter, checker, qaqc), `scripts/` (convert, audit), `static/app.js`, templates. Citations restricted to the PSHA Project Reference Folder (`rd psha/reference/`) per project rules. Baker–Bradley–Stafford textbook cited as `BBS`; printed page = PDF page − 13.

---

## Strengths

1. **The capture audit is the best part of the repo.** `scripts/audit_catalogue.py` independently re-reads the workbook, reconciles all 47,046 data cells 1:1, proves a cell partition (preamble / header / event field), pins the source by sha256, asserts an exact anomaly ledger, and exits non-zero on failure. This is genuinely rigorous provenance work.
2. **No silent fixes.** Anomalies (Hour=27, text-coerced magnitudes, duplicates) are kept raw and flagged in `qa_flags` — the right call for a hazard-input catalogue.
3. **Magnitude preference Mw > Ms > Mb > Ml is defensible.** Moment magnitude is the de facto standard scale for PSHA.
   **Basis:** `Seismic Hazard and Risk Analysis (BBS)`, Sec. 2.8 (Eq. 2.5, Hanks & Kanamori scale), p. 35.
4. **Cumulative-moment constant is correct.** `10**(1.5*M + 9.05)` N·m matches the moment-magnitude definition with M₀ in N·m (the 16.05/dyne-cm form converts to 9.05 in SI).
   **Basis:** `BBS`, Eq. 2.5, p. 35, and the footnote on the original dyne-cm definition, p. 57. (`Hanks, Kanamori, 1979, A Moment Magnitude Scale.pdf` is in the folder but is a scanned PDF; text/page not extractable.)
5. Stepp σλ = √λ/√T implementation, masked-zero log density plots, and HMTK-style structure are clean; matplotlib `Agg` set correctly for server use.

---

## Weaknesses / Gaps

### A. Methodological (highest priority)

**A1. Declustering ignores magnitude ranking — earlier event always wins.**
`_run_decluster` (web_app.py:229–255) marks every later event inside the window of an earlier surviving event as an aftershock, regardless of magnitude. A M7.5 occurring 10 days after a nearby M5.0 is deleted as an "aftershock" of the M5.0. In the GK algorithm the windows are defined around the *mainshock* (the largest event of the cluster), and foreshocks are also removed; neither holds here.
> **Basis:** `BBS`, Sec. 3.3.5 (Data Preparation — Declustering), p. 75: "In the declustering algorithm of Gardner and Knopoff (1974) the temporal and spatial windows defined to identify aftershocks are increasing functions of magnitude. These windows … any event occurring within these ranges is associated with the mainshock." And p. 73: declustering exists to recover the Poisson mainshock rate.

Also: the time window is truncated to whole days (`np.timedelta64(int(sw_time_days[i]), "D")`), discarding the fractional part.

**A2. MFD completeness correction inflates rates.**
`api_mfd` (web_app.py:883–890) counts **all** events in a magnitude bin (whole catalogue span) but divides by the **post-completeness duration** for that bin. Events that occurred before the completeness year stay in the numerator while the denominator shrinks → systematic overestimation of λ. Events must be counted only within their bin's period of completeness.
> **Basis:** `BBS`, Fig. 3.10 caption, p. 78: rates are "obtained from observing the numbers of events … in light of the corresponding period of completeness for each magnitude." See also Completeness Levels, pp. 71–72.

**A3. `Mmax = observed + 0.5` is an uncited flat increment.**
web_app.py:1101 hard-codes `mmax_plus_05`. The Reference Folder supports a statistical increment that depends on the magnitude-frequency distribution and requires iteration — not a constant 0.5.
> **Basis:** `BBS`, Sec. 3.5.4 (Statistical Estimation of mmax), Eq. 3.32, p. 92: Δmmax depends on FMn(m) and "an iterative procedure is required." Supporting source: `kijko2004.pdf` (full estimator derivations; printed page numbers not verified from the extraction).

**A4. GR page applies no completeness handling and mixes estimators.**
`api_gutenberg_richter` fits b by MLE on all events ≥ Mc over the full 1907–2025 span (assuming uniform completeness — contradicted by the catalogue itself), anchors the a-value to a single observed cumulative point, and defaults Mc to the magic number 4.45. The 24 exact duplicate pairs documented in `reports/audit_report.md` are never removed before rate estimation, and nothing enforces that the input was declustered — both violate the Poisson-rate premise.
> **Basis:** `BBS`, Sec. 3.3.5, p. 68 (Poisson-process compatibility requires removing dependent events) and Sec. 3.5.4, p. 92 (estimation "starts by taking a declustered seismicity catalog that is complete above some level mmin"). Duplicates: `reports/audit_report.md` (this repo), Anomaly ledger section.

**A5. b-value formula carries an undocumented bin correction.**
`b = log10(e) / (mean − (Mc − dm/2))` (web_app.py:741, 901). The folder's stated MLE form is `b = log10(e) / (Mmean − MC)` with no Δm/2 term. The correction is probably intentional (binned magnitudes) but has no basis in the Reference Folder and no citation in the code.
> **Basis:** `Homogenized earthquake catalog and bvalue mapping for Ethiopia….pdf` (Lamessa et al.), Eq. (21), p. 7 of 24.

**A6. Three conflicting depth-class conventions.**
`api_catalog_info` uses 0–70/70–300/≥300 ("USGS convention" — no basis in the Reference Folder); the completeness page defaults to 35/70/700 (configurable); `api_mfd` hard-codes 35/70/700 but labels 70–700 km "Deep." Same catalogue, three taxonomies — results across pages are not comparable. The provided Reference Folder does not contain enough basis to fix one convention; this is a user decision to standardize.

**A7. Stepp (1972) method itself cannot be verified from the Reference Folder.**
The folder contains no Stepp paper; `BBS` pp. 71–72 supports statistical completeness estimation generally but not this specific algorithm or its σλ bilinear-fit details. The GK/Grünthal/Uhrhammer window coefficients (e.g., `10^(0.1238M+0.983)`) likewise have no source in the folder. They should each carry a citation comment, or the source papers should be added to `rd psha/reference/`.

### B. Bugs

**B1. `api_max_magnitude` misaligns years and magnitudes** (web_app.py:1068–1077): `mag` is `dropna()`'d, then `years = dt.dt.year.values[:len(mag)]` slices the *unfiltered* datetime array — when any magnitude is NaN, every subsequent (year, mag) pair is shifted. The cumulative-moment plot also assumes the input is time-sorted (true for the default catalogue, not guaranteed for uploads).

**B2. Thread-unsafe module global** (`completeness.py:264–274`): `plot_mag_time_density` mutates the module-level `time_bin_default` via `global`, which `_build_step_curve` reads. Under Flask's threaded server, concurrent requests race. Pass it as a parameter. (`m_max` parameter of `_build_step_curve` is unused.)

**B3. Inconsistent error contracts**: `api_max_magnitude` returns errors as HTTP 200 with an `error` key (web_app.py:1066, 1115); every other route returns 400. The front end must special-case it.

**B4. `read_csv_from_upload`** returns the first separator producing ≥2 columns — a semicolon file with commas embedded in text fields can silently parse wrong. Use `pd.read_csv(..., sep=None, engine="python")` sniffing, and don't swallow all exceptions.

**B5. `read_phivolcs_excel`** (`converter.py:82–85`): the `mag.fillna(result[pref])` line is dead — the following `combine_first` overwrites it. Harmless but confusing next to a "last wins = highest priority" comment.

### C. Security / robustness

**C1. Unbounded uploads**: `MAX_CONTENT_LENGTH = None` plus unlimited form parts (web_app.py:27–29) invites memory-exhaustion DoS. Set a sensible cap (e.g., 50 MB).

**C2. `debug=True`** in `app.run` (web_app.py:1119): the Werkzeug debugger is an RCE vector if the bind address is ever widened or the port forwarded. Gate it on an env var.

**C3. Self-XSS via `innerHTML`**: `static/app.js` injects server JSON (including the uploaded *filename* echoed back as `source`) into `innerHTML` in ~10 places. Escape or use `textContent`.

**C4. Mapbox token** is interpolated into the page (`base.html:41`). Acceptable only for a public, URL-restricted token — worth a README note.

### D. Engineering hygiene

**D1. No tests.** The audit script is a de facto integration test for the converter, but nothing covers declustering, Stepp, GR/MFD math, or the Flask routes. Your own vault standard (psha-mind `CLAUDE.md`: doctest + pytest before commit) would reject this repo. Highest-value targets: golden-ledger test for the converter (the audit ledger is already the fixture), window-function values, b-value on a synthetic catalogue with known b.

**D2. O(n²) pure-Python declustering** with per-pair haversine and row-wise `df.apply` for the 300-km filter. Fine at 3,577 events; will crawl on a regional M≥3 catalogue. Vectorize distances per anchor event.

**D3. `_plot_decluster_time(cat, results, time_col)`** — `time_col` unused. `detect_format` maps any `.xlsx` to "phivolcs" — over-broad if other Excel catalogues ever appear.

---

## Required Improvements (ordered)

1. Fix A1: implement true GK clustering — identify the largest event per cluster as mainshock, remove fore- and aftershocks; keep fractional-day windows.
2. Fix A2: in `api_mfd`, count only events with `year >= compl_year(bin)` before dividing by the effective duration.
3. Fix B1 alignment: build one DataFrame, drop rows where either mag or time is NaN, sort by time, then plot.
4. Replace A3's `+0.5` with the Kijko (2004) iterative estimator, or label the output explicitly as a placeholder lower bound.
5. Unify depth conventions (A6) into one configurable set shared by catalog/completeness/MFD pages.
6. Wire `qaqc.find_duplicates` into the analysis path (or drop the 24 known duplicate rows behind a checkbox) before GR/MFD fitting.
7. Add the security caps (C1–C3) — three small diffs.
8. Add a `tests/` suite seeded from the audit ledger; cite the window/b-value/Mmax sources in docstrings (add GK 1974, Stepp 1972, Uhrhammer 1986, Grünthal to `rd psha/reference/` so the citations can be folder-backed).

---

## Citation Check

| Point | Reference | Clause / Section | Page | Relevance |
| ----- | --------- | ---------------- | ---- | --------- |
| A1 | `BBS` (Baker/Bradley/Stafford 2022) | Sec. 3.3.5, Declustering | pp. 73, 75 | GK windows defined around the mainshock; declustering recovers Poisson rate |
| A2 | `BBS` | Fig. 3.10 + Completeness Levels | pp. 78; 71–72 | Event counts must be taken within each magnitude's period of completeness |
| A3 | `BBS`; `kijko2004.pdf` | Sec. 3.5.4, Eq. 3.32 | p. 92; kijko page n/v | Mmax increment is distribution-dependent and iterative, not flat +0.5 |
| A4 | `BBS`; `reports/audit_report.md` (repo) | Sec. 3.3.5; Sec. 3.5.4 | pp. 68, 92 | Estimation requires declustered, complete catalogue; 24 duplicates documented |
| A5 | `Homogenized earthquake catalog … Ethiopia` (Lamessa et al.) | Eq. (21) | p. 7 of 24 | Folder's MLE b-value form lacks the Δm/2 term used in code |
| S3/S4 | `BBS` | Eq. 2.5 (Sec. 2.8) | pp. 35, 57 | Mw standard scale; M₀ = 10^(1.5M+9.05) N·m constant verified |
| A7 | — | — | — | Stepp (1972), GK (1974), Uhrhammer (1986), Grünthal window coefficients: **no basis in the Reference Folder** |
| A6 | — | — | — | "USGS" depth convention: **no basis in the Reference Folder** |

## Verification Notes

- BBS citations: **Verified from the provided Reference Folder** (printed page = PDF page − 13 convention applied; equation bodies render as images in extraction, so Eq. 3.32 / Eq. 2.5 identification relies on surrounding verified text).
- Lamessa et al. Eq. (21): **Verified from the provided Reference Folder.**
- `kijko2004.pdf`: clause verified from the file's abstract/derivation text; **printed page numbers unclear in the provided extraction** — partially verified.
- Hanks & Kanamori (1979): present in folder but scanned without a text layer — **page number not visible in the provided file**; the constant was instead verified via BBS pp. 35/57.
- Stepp (1972), GK (1974) window coefficients, Uhrhammer, Grünthal, USGS depth classes: **Not verified; the provided Reference Folder does not contain sufficient basis.** Code observations about them are software findings, not folder-cited claims.

## Summary

The data-provenance layer (converter + audit) is excellent and worth keeping as-is. The analysis layer has four substantive methodological defects: declustering that can delete mainshocks (A1), completeness-corrected MFD rates biased high (A2), an uncited flat +0.5 Mmax (A3), and GR fitting on an un-declustered, duplicate-bearing, completeness-uncorrected catalogue (A4) — each contradicting provisions verifiable in `BBS` Secs. 3.3.5/3.5.4 and Fig. 3.10. Key missing references (Stepp 1972, Gardner & Knopoff 1974, Uhrhammer 1986, Grünthal) are not in the Reference Folder; add them so the window coefficients and the Stepp algorithm can be folder-cited. Action needed from you: decide the single depth-class convention (A6) and confirm whether the +0.5 Mmax is a deliberate placeholder.
