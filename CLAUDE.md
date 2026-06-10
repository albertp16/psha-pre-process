# CLAUDE.md — psha-pre-process

Guardrails for any Claude session working in this repo.

## Pipeline order (enforce it)

The correct catalogue-preparation chain, per Baker–Bradley–Stafford (BBS),
*Seismic Hazard and Risk Analysis* (2022), Sec. 3.3.5 checklist, p. 68
(printed page = PDF page − 13; PDF lives in the PSHA vault,
`rd psha/reference/`):

```
1. Harmonize to Mw      (BBS p. 69 — wired in, but OFF until the user supplies
                         cited region-specific coefficients; none are baked in)
2. Remove duplicates    (BBS p. 68 — applied by default on every analysis page)
3. Decluster            (BBS pp. 73, 75 — mainshock = largest in cluster)
4. Completeness         (BBS pp. 71–72)
5. GR / MFD fit         (one stage; rates per completeness period, BBS Fig. 3.10 p. 78)
6. Mmax                 (Kijko–Sellevoll, kijko2004.pdf Eqs. 6–8 pp. 1659–1660)
```

GR and MFD are not separate steps: GR is the model, the MFD is its fitted
product. Steps 5–6 must only consume the output of steps 1–4. The web app
applies steps 1–2 in every analysis route (`_apply_pipeline_pre_steps`) and
offers step 3 on the GR/MFD/Mmax pages (`decluster_first`); when the input
was not declustered it emits a written warning rather than blocking — keep
that warning intact and do not let new code weaken the ordering.

## Reference implementation

`reference/psha_pipeline_reference.py` contains corrected, cited, doctested
versions of each step (harmonization, duplicate removal, GK declustering
with largest-event mainshock + foreshock removal, completeness-corrected
rates, Aki/Shi–Bolt b-value, Kijko–Sellevoll Mmax). The production port is
`psha_preprocess/catalogue/pipeline.py` — keep the two in sync; `web_app.py`
must call the pipeline module, not reimplement the math. Run:

```bash
python3 -m doctest reference/psha_pipeline_reference.py
python3 -m doctest psha_preprocess/catalogue/pipeline.py
```

All functions must keep their docstring citation + passing doctest
(same convention as the psha-mind vault).

## Citations

Technical claims cite only files in the PSHA vault Reference Folder
(`~/Desktop/PSHA/PSHA Project/rd psha/reference/`), with file, section,
and page. Known gaps — these sources are NOT in the folder; do not cite
them as if verified, and prefer adding the PDFs to the folder first:

- Gardner & Knopoff (1974) — window coefficients in `decluster_windows()`
  (pipeline module + reference `gk_windows()`) are uncited (HMTK-heritage values).
- Stepp (1972) — completeness algorithm in `psha_preprocess/catalogue/completeness.py`.
- Uhrhammer (1986), Grünthal — alternative decluster windows (same function).
- Philippines-specific Ms/Mb/Ml→Mw conversion relations — required for
  step 1; the example coefficients in the reference file are placeholders,
  which is why the web app ships with harmonization off by default.
- The dm/2 b-value binning correction (Utsu 1965/Bender 1983) — exposed as
  the off-by-default `bin_correction` form flag; do not turn it on by default.

## Defect ledger (from CODE_REVIEW.md — read it before editing)

Fixed in the 2026-06 tool update (regression-guarded by `tests/`):

- A1 `_run_decluster` deleted later, larger events — now largest-first with
  foreshock removal via `pipeline.gardner_knopoff_decluster`.
- A2 `api_mfd` counted all events over post-completeness durations — now
  `pipeline.completeness_rates` (count and duration both completeness-bound).
- A3/B1 `api_max_magnitude` year/magnitude misalignment fixed; the uncited
  `Mmax = observed + 0.5` replaced by Kijko–Sellevoll (`results` key
  `mmax_kijko_sellevoll`).
- A6 depth classes unified to 35/70/700 km (`DEPTH_BOUNDS_KM`, project
  convention — still no folder basis; change it only there).
- C1/C2 upload cap 50 MB; `debug` now gated on `FLASK_DEBUG=1`.

Still open:

- Steps 5–6 warn rather than hard-block on un-declustered input.
- The combined TruncatedGR fit on the MFD page uses the whole-span duration
  (no whole-catalogue completeness table exists on that page); it says so in
  its QA/QC warning.
- Stepp σλ bilinear-fit details remain unverifiable from the Reference Folder.

## Testing

`tests/` holds the pytest suite (pipeline unit tests + endpoint smoke tests
against the bundled catalogue). Any new analysis code needs a doctest and a
pytest check. The audit ledger in `scripts/audit_catalogue.py` (sha-keyed
expected counts) is the fixture of record for converter changes — keep both
passing:

```bash
python3 -m pytest tests/ -q            # all green required
python scripts/audit_catalogue.py      # exit 0 required
```
