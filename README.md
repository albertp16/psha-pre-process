# PSHA Pre-Process

Catalogue pre-processing web app for Probabilistic Seismic Hazard Analysis, built around the
**PHIVOLCS Earthquake Catalogue of the Philippines** (1907–2025, 3,577 events, M ≥ ~5).
Ported from `seismicprocesspy` (sibling repo at `Desktop\seismicprocesspy`): Declustering, Completeness
Analysis, Gutenberg-Richter, MFD, and Max Magnitude, plus Mapbox epicenter maps.

## Quick start

```bash
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python web_app.py        # http://127.0.0.1:5000
```

The **Catalog** page shows the full PHIVOLCS catalogue on a Mapbox map with the capture-audit
status. Every analysis page has *"Use PHIVOLCS default catalog"* pre-ticked; uploading a CSV
overrides it. Maps need a Mapbox token: set the `MAPBOX_TOKEN` env var, drop it in an
untracked `mapbox_token.txt` next to `web_app.py`, or paste it into the token field in the UI.

## Data pipeline

| Step | Script | Output |
|---|---|---|
| Convert | `scripts/convert_catalogue.py` | `data/catalog.json` (full fidelity + metadata), `data/catalog.geojson` (Mapbox-ready, no intensity text) |
| Audit | `scripts/audit_catalogue.py` | `reports/audit_report.md`, `reports/audit.json` (exit 1 on capture failure) |

Source workbook: `data/source/Earthquake Catalogue of the Philippines.xlsx`
(sheets `1907-2018` + `2019-2025`, header row 9, data from row 12).

### Conversion rules
- Every non-empty workbook cell lands in exactly one bucket: preamble metadata, header
  metadata, or an event field — the audit proves the partition and reconciles all
  47,046 data cells 1:1 (float tol 1e-9, text exact).
- Magnitudes kept raw per type (`ml`, `mb`, `ms`, `mw`); preferred `mag` = first available of
  **Mw > Ms > Mb > Ml**, recorded in `mag_type`. No empirical conversion.
- No silent fixes: anomalies are kept raw and flagged in `qa_flags`.

### Known source-data anomalies (audited)
- Ml/Mb stored as text in the 1907–2018 sheet (1,250 + 1,855 cells) — coerced, flagged.
- One event (2019–2025 sheet, row 329; 2023-02-24, Mw 5.0) has `Hour = 27` → `datetime_utc`
  null, excluded from time-based analyses, still on the map.
- 24 exact duplicate origin-time+location pairs (e.g. rows 323–327 repeated as 328–332).
- Preamble region/period text does not match the actual data span (documented in
  `metadata.notes`).

## Layout

```
web_app.py                    Flask app: 5 analysis APIs + catalog endpoints
psha_preprocess/catalogue/    completeness (Stepp 1972), checker, converter, qaqc
scripts/                      convert_catalogue.py, audit_catalogue.py
data/                         source xlsx, catalog.json, catalog.geojson
reports/                      audit_report.md, audit.json
templates/, static/           sidebar UI (Catalog, Declustering, Completeness, GR, MFD, Mmax)
```
