"""
PSHA Pre-Process - PHIVOLCS Earthquake Catalogue
Catalogue pre-processing for Probabilistic Seismic Hazard Analysis
Developed by Albert Pamonag and Camille Pajarillaga

Flask backend. Ported from seismicprocesspy (Declustering, Completeness,
Gutenberg-Richter, MFD, Max Magnitude + Mapbox maps), preloaded with the
PHIVOLCS catalogue converted by scripts/convert_catalogue.py.
"""

import io
import json
import math
import base64
import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from flask import Flask, render_template, request, jsonify, send_file

from psha_preprocess.catalogue import pipeline as pl

app = Flask(__name__)
# Upload caps (CODE_REVIEW C1): unbounded uploads invite memory-exhaustion DoS.
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
app.config["MAX_FORM_MEMORY_SIZE"] = 50 * 1024 * 1024
app.config["MAX_FORM_PARTS"] = 1000

APP_VERSION = "1.0.0"

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_CATALOG_LABEL = "PHIVOLCS Earthquake Catalogue of the Philippines"

# Mapbox token: env var, else untracked mapbox_token.txt next to this file,
# else maps prompt for a token in the UI.
MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN", "")
_token_file = REPO_ROOT / "mapbox_token.txt"
if not MAPBOX_TOKEN and _token_file.exists():
    MAPBOX_TOKEN = _token_file.read_text(encoding="utf-8").strip()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def read_csv_from_upload(file_storage) -> pd.DataFrame:
    raw = file_storage.read()
    # csv.Sniffer-based separator detection (CODE_REVIEW B4): trying fixed
    # separators in order can silently mis-parse e.g. semicolon files with
    # embedded commas.
    try:
        df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python")
        if df.shape[1] >= 2:
            return df
    except (pd.errors.ParserError, UnicodeDecodeError, ValueError):
        pass
    return pd.read_csv(io.BytesIO(raw))


def fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def df_to_csv_str(df: pd.DataFrame) -> str:
    return df.to_csv(index=False)


def to_datetime_safe(s: pd.Series) -> pd.Series:
    """Parse datetimes tolerantly (mixed precisions/formats -> NaT, never raises)."""
    for kwargs in ({"utc": True}, {"utc": True, "format": "mixed"}):
        try:
            return pd.to_datetime(s, errors="coerce", **kwargs)
        except (ValueError, TypeError):
            continue
    return pd.Series(pd.NaT, index=s.index)


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat, dlon = rlat2 - rlat1, rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Focal-depth convention (single project-wide taxonomy, CODE_REVIEW A6) ──
# One set of class bounds shared by the Catalog, Declustering, Completeness
# (as defaults) and MFD pages so results are comparable across pages.
# The bounds are a project convention (the PSHA Reference Folder contains no
# basis for any specific taxonomy); they keep the completeness page's
# long-standing configurable defaults.
DEPTH_BOUNDS_KM = (35.0, 70.0, 700.0)
DEPTH_CLASS_LABELS = {
    "shallow": f"Shallow (0–{DEPTH_BOUNDS_KM[0]:.0f} km)",
    "intermediate": f"Mid-depth ({DEPTH_BOUNDS_KM[0]:.0f}–{DEPTH_BOUNDS_KM[1]:.0f} km)",
    "deep": f"Deep ({DEPTH_BOUNDS_KM[1]:.0f}–{DEPTH_BOUNDS_KM[2]:.0f} km)",
}
DEPTH_CONVENTION_NOTE = (
    f"Depth classes: shallow 0–{DEPTH_BOUNDS_KM[0]:.0f}, "
    f"mid-depth {DEPTH_BOUNDS_KM[0]:.0f}–{DEPTH_BOUNDS_KM[1]:.0f}, "
    f"deep {DEPTH_BOUNDS_KM[1]:.0f}–{DEPTH_BOUNDS_KM[2]:.0f} km "
    "(project convention, uniform across pages)."
)


def depth_class_counts(depths) -> dict:
    """Event counts per unified depth class; 'unknown' = missing/out of range."""
    d = pd.to_numeric(pd.Series(depths), errors="coerce")
    s0, s1, s2 = DEPTH_BOUNDS_KM
    return {
        "shallow": int(((d >= 0) & (d < s0)).sum()),
        "intermediate": int(((d >= s0) & (d < s1)).sum()),
        "deep": int(((d >= s1) & (d < s2)).sum()),
        "unknown": int(len(d) - ((d >= 0) & (d < s2)).sum()),
    }


# ── Catalogue-preparation steps 1–3 (BBS Sec. 3.3.5 checklist, p. 68) ──
def _parse_harmonize_coeffs(text):
    """Parse 'scale,slope,intercept' lines -> ({scale: (slope, intercept)}, bad_lines)."""
    coeffs, bad = {}, []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3 or not parts[0]:
            if line.strip():
                bad.append(line.strip())
            continue
        try:
            coeffs[parts[0]] = (float(parts[1]), float(parts[2]))
        except ValueError:
            bad.append(line.strip())
    return coeffs, bad


def _has_datetime_time(cat) -> bool:
    return "_time" in cat.columns and np.issubdtype(
        np.asarray(cat["_time"].values).dtype, np.datetime64)


def _mw_breakdown(srcs):
    """Human-readable per-source counts from homogenize_to_mw labels."""
    order = (("mw", "reported Mw"), ("ms2mw", "Ms→Mw"), ("mb2mw", "mb→Mw"),
             ("user_coeffs", "user-coefficient"), ("raw", "kept as reported"))
    return ", ".join(f"{srcs[k]} {lbl}" for k, lbl in order if srcs.get(k))


def _apply_pipeline_pre_steps(cat, form, notes):
    """Steps 1–2 of the catalogue-preparation chain, in order.

    Step 1 homogenize to Mw (BBS p. 69) — ON by default using the
    folder-cited global relations (reported Mw > Ms→Mw > mb→Mw, Scordilis
    2006 via Lamessa p. 5), applied only inside their validity ranges.
    User-supplied 'scale,slope,intercept' coefficient lines override the
    cited defaults; `homogenize=0` disables the step.
    Step 2 remove duplicates (BBS p. 68) — default ON, needs lat/lon and a
    datetime time column.

    Returns (catalogue, info) where info may carry 'mw_sources' counts;
    appends QA/QC lines to `notes`. Raises ValueError on unusable input.
    """
    info = {}
    text = form.get("harmonize_coeffs", "").strip()
    if text:
        coeffs, bad = _parse_harmonize_coeffs(text)
        scale_col = form.get("mag_type_col", "mag_type")
        if not coeffs:
            raise ValueError(
                "Harmonization coefficients given but no 'scale,slope,intercept' "
                "line could be parsed")
        if scale_col not in cat.columns:
            raise ValueError(
                f"Harmonization needs a magnitude-scale column '{scale_col}' "
                "(set mag_type_col)")
        mw, conv = pl.harmonize_to_mw(
            cat["_mag"].values, cat[scale_col].astype(str).values, coeffs)
        cat = cat.copy()
        cat["_mag"] = mw
        cat["mag_mw"] = mw  # propagated to CSV downloads
        cat["mag_mw_src"] = np.where(conv, "user_coeffs", "raw")
        info["mw_sources"] = {"user_coeffs": int(conv.sum()),
                              "raw": int((~conv).sum())}
        notes.append(
            f"Step 1 harmonization: {int(conv.sum())} magnitudes converted to Mw "
            f"with user-supplied coefficients ({', '.join(sorted(coeffs))}); "
            f"{int((~conv).sum())} left unchanged (BBS p. 69 — coefficients must "
            "be region-specific and cited by the user).")
        if bad:
            notes.append(f"Harmonization: {len(bad)} unparsable line(s) ignored.")
    elif form.get("homogenize", "1") == "1":
        # Cited global defaults: reported Mw > Ms->Mw > mb->Mw (Scordilis 2006
        # via Lamessa p. 5), each applied only inside its validity range so the
        # largest events (e.g. Ms 8.3) are never extrapolated.
        def _col(name):
            col = form.get(f"{name}_col", name)
            if col in cat.columns:
                vals = pd.to_numeric(cat[col], errors="coerce")
                if vals.notna().any():
                    return vals.values
            return None

        mw_v, ms_v, mb_v = _col("mw"), _col("ms"), _col("mb")
        if mw_v is None and ms_v is None and mb_v is None:
            notes.append(
                "Step 1 homogenization: skipped — no mw/ms/mb scale columns "
                "found; magnitudes used as reported (BBS p. 69).")
        else:
            mw_est, src = pl.homogenize_to_mw(
                mw=mw_v, ms=ms_v, mb=mb_v, fallback=cat["_mag"].values)
            cat = cat.copy()
            cat["_mag"] = mw_est
            cat["mag_mw"] = mw_est        # propagated to CSV downloads
            cat["mag_mw_src"] = src       # per-event provenance
            labels, counts = np.unique(src, return_counts=True)
            srcs = {str(l): int(c) for l, c in zip(labels, counts)}
            info["mw_sources"] = srcs
            notes.append(
                "Step 1 homogenization to Mw: " + _mw_breakdown(srcs)
                + " — reported Mw preferred; conversions applied only inside "
                  "their validity ranges (BBS p. 69; Lamessa p. 5, Scordilis "
                  "2006 Eqs. 1/8 — global relations, not Philippines-specific).")
            present = np.zeros(len(src), dtype=bool)
            if ms_v is not None:
                present |= ~np.isnan(ms_v)
            if mb_v is not None:
                present |= ~np.isnan(mb_v)
            n_oor = int(((src == "raw") & present).sum())
            n_noscale = srcs.get("raw", 0) - n_oor
            if n_oor:
                notes.append(
                    f"{n_oor} kept-as-reported event(s) have Ms/mb outside the "
                    "relations' ranges (Ms 3.0–6.1, mb 3.5–6.2; includes the "
                    "largest events) — left unconverted rather than "
                    "extrapolated.")
            if n_noscale > 0:
                notes.append(
                    f"{n_noscale} event(s) have no Mw/Ms/mb (Ml-only): no "
                    "folder-backed Ml→Mw relation; kept as reported.")
    else:
        notes.append(
            "Step 1 homogenization: disabled by user — magnitudes used as "
            "reported (BBS p. 69 requires one consistent Mw scale before "
            "rate fitting).")

    if form.get("dedup", "1") == "1":
        if {"_lat", "_lon"}.issubset(cat.columns) and _has_datetime_time(cat):
            t_s = _times_to_days(cat["_time"]) * 86400.0
            keep = pl.remove_duplicates(
                t_s, cat["_lat"].values, cat["_lon"].values, cat["_mag"].values)
            n_dup = int((~keep).sum())
            cat = cat[keep].reset_index(drop=True)
            notes.append(f"Step 2 duplicates: {n_dup} removed (BBS p. 68).")
        else:
            notes.append(
                "Step 2 duplicates: skipped — needs lat/lon columns and a "
                "datetime time column.")
    else:
        notes.append(
            "Step 2 duplicates: disabled by user (BBS p. 68: each event must "
            "be represented only once).")
    return cat, info


def _events_detail_payload(cat, mag_col, form, src_arr, mw_used, moment):
    """Per-event rows for the clickable catalogue tables (Mw basis + moment),
    plus the relation constants the client needs to render the computation
    in LaTeX (Scordilis via Lamessa p. 5; Hanks–Kanamori Eq. 7 p. 2349)."""
    def _col_list(name):
        col = form.get(f"{name}_col", name)
        if col in cat.columns:
            v = pd.to_numeric(cat[col], errors="coerce")
            return [None if pd.isna(x) else round(float(x), 2) for x in v]
        return [None] * len(cat)

    ids = (cat["id"].astype(str).tolist() if "id" in cat.columns
           else [str(i + 1) for i in range(len(cat))])
    if _has_datetime_time(cat):
        dates = cat["_time"].dt.strftime("%Y-%m-%d").tolist()
    else:
        dates = [f"{y:.2f}" for y in cat["_year"]]
    mtypes = (cat["mag_type"].astype(str).tolist()
              if "mag_type" in cat.columns else [""] * len(cat))
    reported = [None if pd.isna(x) else round(float(x), 2)
                for x in pd.to_numeric(cat[mag_col], errors="coerce")]

    events_detail = [
        {"id": i_, "date": d_, "ml": ml_, "mb": mb_, "ms": ms_, "mw": mw_,
         "mag": rep_, "mag_type": mt_, "src": str(s_),
         "mw_used": round(float(mwu_), 3), "m0": float(m0_)}
        for i_, d_, ml_, mb_, ms_, mw_, rep_, mt_, s_, mwu_, m0_ in zip(
            ids, dates, _col_list("ml"), _col_list("mb"), _col_list("ms"),
            _col_list("mw"), reported, mtypes, src_arr, mw_used, moment)
    ]

    rel_ms = pl.MS_RELATIONS["scordilis2006"]
    rel_mb = pl.MB_RELATIONS["scordilis2006"]
    moment_relations = {
        "ms": {"a": rel_ms[0], "b": rel_ms[1], "lo": rel_ms[2], "hi": rel_ms[3],
               "cite": "Scordilis 2006, Eq. 8 — Lamessa et al. 2019, p. 5"},
        "mb": {"a": rel_mb[0], "b": rel_mb[1], "lo": rel_mb[2], "hi": rel_mb[3],
               "cite": "Scordilis 2006, Eq. 1 — Lamessa et al. 2019, p. 5"},
        "moment_cite": "Hanks & Kanamori 1979, Eq. 7, p. 2349; "
                       "BBS Eq. 2.5, pp. 35/57",
        "mw_cite": "BBS Sec. 3.3.5, p. 69 — reported Mw preferred",
        "b_cite": "Aki MLE — Lamessa et al. 2019, Eqs. 21–22, p. 7",
        "mmax_cite": "Kijko 2004, Eqs. 6–8, pp. 1659–1660",
    }
    return events_detail, moment_relations


def _maybe_decluster_first(cat, form, notes):
    """Optional step 3 for the rate-fitting pages (GR/MFD/Mmax).

    BBS p. 68: Poisson-rate estimation requires removing dependent events;
    p. 92: estimation 'starts by taking a declustered seismicity catalog'.
    GK windows, mainshock = largest event of the cluster.
    """
    if form.get("decluster_first", "0") != "1":
        return cat, False
    if not ({"_lat", "_lon"}.issubset(cat.columns) and _has_datetime_time(cat)):
        notes.append(
            "Step 3 declustering: requested but skipped — needs lat/lon "
            "columns and a datetime time column.")
        return cat, False
    is_main = _run_decluster(cat, "gk")
    n_dep = int((~is_main).sum())
    cat = cat[is_main].reset_index(drop=True)
    notes.append(
        f"Step 3 declustering (GK windows, mainshock = largest in cluster): "
        f"{n_dep} fore/aftershocks removed (BBS pp. 73, 75).")
    return cat, True


# ── Default catalog (PHIVOLCS JSON produced by scripts/convert_catalogue.py) ──
_default_catalog_df = None
_default_catalog_meta = None


def _load_default_catalog():
    global _default_catalog_df, _default_catalog_meta
    if _default_catalog_df is None:
        payload = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
        _default_catalog_meta = payload["metadata"]
        df = pd.DataFrame(payload["events"])
        df = df.rename(columns={"depth_km": "depth"})
        # Parse once here: the ISO strings mix second/sub-second precision, which
        # pandas 3 won't infer as a single format inside the analysis routes.
        df["time"] = pd.to_datetime(df["datetime_utc"], format="ISO8601", utc=True, errors="coerce")
        # One event (2023-02-24, Hour=27) has no valid datetime: excluded from
        # time-based analyses; it remains in catalog.json / the map.
        df = df[df["time"].notna()].reset_index(drop=True)
        keep = ["id", "source_sheet", "source_row", "year", "month", "day", "hour",
                "minute", "second", "time", "latitude", "longitude", "depth",
                "ml", "mb", "ms", "mw", "mag", "mag_type"]
        _default_catalog_df = df[[c for c in keep if c in df.columns]]
    return _default_catalog_df.copy(), _default_catalog_meta


def get_catalog_input(req):
    """Resolve the catalogue for an analysis request.

    Returns (df, source_label, error). An uploaded file wins; otherwise the
    PHIVOLCS default catalog is used when use_default=1.
    """
    f = req.files.get("file")
    if f and f.filename:
        try:
            return read_csv_from_upload(f), f.filename, None
        except Exception as e:
            return None, None, str(e)
    if req.form.get("use_default") == "1":
        try:
            df, _ = _load_default_catalog()
            return df, DEFAULT_CATALOG_LABEL, None
        except Exception as e:
            return None, None, f"Default catalog not available ({e}); run scripts/convert_catalogue.py"
    return None, None, "No file uploaded (or tick 'Use PHIVOLCS default catalog')"


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("base.html", version=APP_VERSION, mapbox_token=MAPBOX_TOKEN)


@app.route("/data/catalog.json")
def serve_catalog_json():
    return send_file(DATA_DIR / "catalog.json", mimetype="application/json")


@app.route("/data/catalog.geojson")
def serve_catalog_geojson():
    return send_file(DATA_DIR / "catalog.geojson", mimetype="application/geo+json")


@app.route("/api/catalog_info")
def api_catalog_info():
    """Summary of the bundled PHIVOLCS catalogue + audit status for the Catalog page."""
    try:
        payload = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return jsonify(available=False,
                       error="data/catalog.json missing - run scripts/convert_catalogue.py")
    meta = payload["metadata"]
    events = payload["events"]

    mags = np.array([ev["mag"] for ev in events if ev["mag"] is not None], dtype=float)
    mag_bins = {
        "lt4": int((mags < 4.0).sum()),
        "m4": int(((mags >= 4.0) & (mags < 5.0)).sum()),
        "m5": int(((mags >= 5.0) & (mags < 6.0)).sum()),
        "m6": int(((mags >= 6.0) & (mags < 7.0)).sum()),
        "ge7": int((mags >= 7.0).sum()),
    }
    depth_classes = depth_class_counts([ev["depth_km"] for ev in events])

    audit = None
    audit_path = REPORTS_DIR / "audit.json"
    if audit_path.exists():
        a = json.loads(audit_path.read_text(encoding="utf-8"))
        audit = {
            "status": a.get("status"),
            "generated_utc": a.get("generated_utc"),
            "n_failures": len(a.get("failures", [])),
            "n_warnings": len(a.get("warnings", [])),
            "warnings": a.get("warnings", []),
            "counts": a.get("counts", {}),
        }

    n_no_dt = sum(1 for ev in events if ev["datetime_utc"] is None)
    return jsonify(
        available=True,
        label=DEFAULT_CATALOG_LABEL,
        source_file=meta["source_file"],
        source_sha256=meta["source_sha256"],
        total_events=meta["total_events"],
        year_min=meta["year_min"],
        year_max=meta["year_max"],
        catalog_period=f"{meta['year_min']}–{meta['year_max']}",
        mag_type_counts=meta["mag_type_counts"],
        qa_flag_counts=meta["qa_flag_counts"],
        magnitude_preference=meta["magnitude_preference"],
        notes=meta["notes"],
        mag_bins=mag_bins,
        depth_classes=depth_classes,
        depth_class_labels=DEPTH_CLASS_LABELS,
        depth_convention_note=DEPTH_CONVENTION_NOTE,
        n_total=meta["total_events"],
        n_excluded_from_analysis=n_no_dt,
        audit=audit,
    )


# ── Moment Magnitude (workflow item 1: homogenize to Mw) ─────────────
@app.route("/api/moment_magnitude", methods=["POST"])
def api_moment_magnitude():
    """Step 1 of the catalogue chain as its own page (BBS Sec. 3.3.5, p. 69):
    homogenize the mixed-scale catalogue to Mw and show the per-event basis."""
    mag_col = request.form.get("mag_col", "mag")
    time_col = request.form.get("time_col", "time")

    df, src_label, err = get_catalog_input(request)
    if err:
        return jsonify(error=err), 400
    if mag_col not in df.columns or time_col not in df.columns:
        return jsonify(error=f"Columns '{mag_col}'/'{time_col}' not found"), 400

    cat = df.copy()
    cat["_mag"] = pd.to_numeric(cat[mag_col], errors="coerce")
    parsed = to_datetime_safe(cat[time_col])
    if parsed.notna().any():
        cat["_time"] = parsed
        cat["_year"] = parsed.dt.year + parsed.dt.dayofyear / 365.25
    else:
        cat["_year"] = pd.to_numeric(cat[time_col], errors="coerce")
    cat = cat.dropna(subset=["_mag", "_year"]).sort_values("_year").reset_index(drop=True)
    n_input = len(cat)
    if n_input == 0:
        return jsonify(error="No valid rows after parsing"), 400

    # This page IS step 1 — run it alone; steps 2–3 belong to the later pages.
    notes, warnings = [], []
    form = dict(request.form.items())
    form["homogenize"] = form.get("homogenize", "1")
    form["dedup"] = "0"
    try:
        cat, _info = _apply_pipeline_pre_steps(cat, form, notes)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    notes = [n for n in notes if not n.startswith("Step 2")]
    notes.append("Step 2 (duplicates) and step 3 (declustering) are applied "
                 "on the analysis pages (BBS p. 68).")

    if "mag_mw_src" in cat.columns:
        src_arr = cat["mag_mw_src"].astype(str).values
    else:
        src_arr = np.full(len(cat), "raw", dtype=object)
        warnings.append("Homogenization did not run — magnitudes left as "
                        "reported (one consistent Mw scale is required before "
                        "rate fitting, BBS p. 69).")

    mw_used = cat["_mag"].values
    moment = pl.seismic_moment_nm(mw_used)
    events_detail, moment_relations = _events_detail_payload(
        cat, mag_col, request.form, src_arr, mw_used, moment)
    labels, cnts = np.unique(src_arr, return_counts=True)
    counts = {str(l): int(c) for l, c in zip(labels, cnts)}

    # Figure 1.1 — comparative two-panel figure: (a) the catalogue as
    # reported (mixed scales) vs (b) the same events homogenized to Mw,
    # coloured by the per-event conversion basis.
    years = cat["_year"].values
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2),
                                   sharex=True, sharey=True)

    scale_colors = {"Mw": "#2563eb", "Ms": "#f59e0b",
                    "Mb": "#16a34a", "Ml": "#9ca3af"}
    reported_mag = pd.to_numeric(cat[mag_col], errors="coerce").values
    if "mag_type" in cat.columns:
        mtypes = cat["mag_type"].astype(str).values
        for sc in ["Ml", "Mb", "Ms", "Mw"]:
            m = mtypes == sc
            if m.any():
                ax1.plot(years[m], reported_mag[m], "o", markersize=3,
                         alpha=0.55, markeredgewidth=0,
                         color=scale_colors[sc],
                         label=f"{sc} ({int(m.sum())})")
    else:
        ax1.plot(years, reported_mag, "o", markersize=3, alpha=0.5,
                 markeredgewidth=0, color="#9ca3af", label="reported")
    ax1.set_title("(a) Reported magnitudes — mixed scales", fontsize=11)
    ax1.set_xlabel("Year", fontsize=11)
    ax1.set_ylabel("Magnitude", fontsize=11)
    ax1.legend(fontsize=8, framealpha=0.9, title="Preferred scale",
               title_fontsize=8)
    ax1.grid(True, linestyle="--", alpha=0.35)

    colors = {"raw": "#9ca3af", "mb2mw": "#16a34a", "ms2mw": "#f59e0b",
              "mw": "#2563eb", "user_coeffs": "#9333ea"}
    label_names = {"raw": "kept as reported", "mb2mw": "mb→Mw",
                   "ms2mw": "Ms→Mw", "mw": "reported Mw",
                   "user_coeffs": "user coefficients"}
    for key in ["raw", "mb2mw", "ms2mw", "mw", "user_coeffs"]:
        m = src_arr == key
        if m.any():
            ax2.plot(years[m], mw_used[m], "o", markersize=3,
                     alpha=0.55, markeredgewidth=0, color=colors[key],
                     label=f"{label_names[key]} ({int(m.sum())})")
    ax2.set_title("(b) Homogenized to Mw — per-event basis", fontsize=11)
    ax2.set_xlabel("Year", fontsize=11)
    ax2.legend(fontsize=8, framealpha=0.9, title="Mw basis",
               title_fontsize=8)
    ax2.grid(True, linestyle="--", alpha=0.35)

    fig.tight_layout()

    out_cols = [c for c in df.columns if c in cat.columns]
    out_cols += [c for c in ("mag_mw", "mag_mw_src") if c in cat.columns]
    csv_str = cat[out_cols].to_csv(index=False)

    qaqc_parts = [f"Source: {src_label}.", f"Input: {n_input} events."]
    qaqc_parts.extend(notes)
    qaqc_parts.extend(f"WARNING: {w}" for w in warnings)

    return jsonify(
        plot=fig_to_b64(fig),
        counts=counts,
        n_input=n_input,
        total_events=int(len(cat)),
        events_detail=events_detail,
        moment_relations=moment_relations,
        csv=csv_str,
        pipeline_notes=notes,
        warnings=warnings,
        source=src_label,
        qaqc=" ".join(qaqc_parts),
    )


# ── Declustering ──────────────────────────────
def _times_to_days(time_series) -> np.ndarray:
    """Datetime series -> float days since epoch (keeps fractional days)."""
    t_ns = np.asarray(time_series.values, dtype="datetime64[ns]").astype(np.int64)
    return t_ns / (1e9 * 86400.0)


def _run_decluster(cat, method):
    """Window declustering, mainshock = largest event of the cluster.

    Delegates to psha_preprocess.catalogue.pipeline.gardner_knopoff_decluster
    (BBS Sec. 3.3.5, pp. 73, 75): events are classified largest-magnitude-
    first so a later, larger event is never deleted as the "aftershock" of a
    smaller one, foreshocks are removed too, and the time window keeps its
    fractional-day part (CODE_REVIEW A1).

    Returns boolean array (True = mainshock).
    """
    return pl.gardner_knopoff_decluster(
        _times_to_days(cat["_time"]),
        cat["_lat"].values, cat["_lon"].values, cat["_mag"].values,
        method=method)


def _plot_decluster_map(cat, is_main, site_lat, site_lon, label, color):
    """Generate declustered scatter map for one method."""
    main = cat[is_main]
    after = cat[~is_main]
    fig, ax = plt.subplots(figsize=(10, 8))
    if not after.empty:
        ax.scatter(after["_lon"], after["_lat"], s=5, c="gray", alpha=0.2,
                   label=f"Aftershocks ({len(after)})")
    sc = ax.scatter(main["_lon"], main["_lat"], s=main["_mag"] ** 2 * 3,
                    c=main["_mag"], cmap="YlOrRd", edgecolors="k",
                    linewidths=0.3, alpha=0.8, label=f"Mainshocks ({len(main)})")
    ax.plot(site_lon, site_lat, "b*", markersize=15, label="Site")
    ax.add_patch(plt.Circle((site_lon, site_lat), 300 / 111.32,
                             fill=False, color="blue", linestyle="--", label="300 km"))
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(f"Declustered – {label} ({len(main)} mainshocks)")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_aspect("equal")
    plt.colorbar(sc, ax=ax, label="Magnitude")
    ax.grid(True, alpha=0.3)
    return fig


def _plot_decluster_time(cat, results):
    """Generate magnitude-time scatter comparing all methods with original."""
    dt = cat["_time"]
    dec_year = dt.dt.year + dt.dt.dayofyear / 365.25
    mag = cat["_mag"].values

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(dec_year, mag, "o", markersize=3, alpha=0.15, color="gray", label="All events")

    colors = {"gk": "#22c55e", "gr": "#ef4444", "uh": "#3b82f6"}
    labels = {"gk": "GK (1974)", "gr": "Grünthal", "uh": "Uhrhammer (1986)"}
    for key, is_main in results.items():
        m = cat[is_main]
        yr = dec_year[is_main]
        ax.plot(yr, m["_mag"], "o", markersize=4, alpha=0.5,
                color=colors[key], label=f"{labels[key]} ({is_main.sum()})")

    ax.set_xlabel("Year")
    ax.set_ylabel("Magnitude")
    ax.set_title("Magnitude-Time: Original vs Declustered")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()
    return fig


def _plot_window_comparison(methods):
    """Plot distance (km) and time (days) windows for all selected methods."""
    mags = np.arange(4.0, 8.6, 0.1)
    colors = {"gk": "green", "gr": "red", "uh": "blue"}
    markers = {"gk": "s", "gr": "^", "uh": "o"}
    labels = {"gk": "Gardner & Knopoff (1974)", "gr": "Gruenthal", "uh": "Uhrhammer (1986)"}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    for m in methods:
        sw_space, sw_time_days = pl.decluster_windows(mags, m)
        ax1.semilogy(mags, sw_space, color=colors[m], marker=markers[m],
                     markersize=5, label=labels[m], linewidth=1)
        ax2.semilogy(mags, sw_time_days, color=colors[m], marker=markers[m],
                     markersize=5, label=labels[m], linewidth=1)

    ax1.set_xlabel("Magnitude")
    ax1.set_ylabel("Distance (km)")
    ax1.set_title("Distance Windows")
    ax1.legend(fontsize=8)
    ax1.grid(True, which="both", linestyle="--", alpha=0.4)
    ax1.set_xlim(4, 8.5)

    ax2.set_xlabel("Magnitude")
    ax2.set_ylabel("Time (days)")
    ax2.set_title("Time Windows")
    ax2.legend(fontsize=8)
    ax2.grid(True, which="both", linestyle="--", alpha=0.4)
    ax2.set_xlim(4, 8.5)

    plt.tight_layout()
    return fig


def _plot_mag_time_scatter(cat, is_main, label):
    """Magnitude-time scatter for original (top) vs declustered (bottom)."""
    dt = cat["_time"]
    dec_year = dt.dt.year + dt.dt.dayofyear / 365.25
    mag = cat["_mag"].values

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ax1.plot(dec_year, mag, "o", markersize=3, alpha=0.6, color="#3b82f6")
    ax1.set_ylabel("Magnitude")
    ax1.set_title(f"Original Catalogue ({len(cat)} events)")
    ax1.grid(True, linestyle="--", alpha=0.4)

    main_yr = dec_year[is_main]
    main_mag = mag[is_main]
    ax2.plot(main_yr, main_mag, "o", markersize=3, alpha=0.6, color="#3b82f6")
    ax2.set_xlabel("Year")
    ax2.set_ylabel("Magnitude")
    ax2.set_title(f"Declustered – {label} ({is_main.sum()} mainshocks)")
    ax2.grid(True, linestyle="--", alpha=0.4)

    plt.tight_layout()
    return fig


@app.route("/api/declustering", methods=["POST"])
def api_declustering():
    lat_col = request.form.get("lat_col", "latitude")
    lon_col = request.form.get("lon_col", "longitude")
    mag_col = request.form.get("mag_col", "mag")
    time_col = request.form.get("time_col", "time")
    depth_col = request.form.get("depth_col", "depth")
    # Fallbacks mirror the frontend's default site preset (Project Site)
    site_lat = float(request.form.get("site_lat", 14.62758))
    site_lon = float(request.form.get("site_lon", 121.08727))

    methods = []
    if request.form.get("use_gk", "1") == "1":
        methods.append("gk")
    if request.form.get("use_gr", "1") == "1":
        methods.append("gr")
    if request.form.get("use_uh", "1") == "1":
        methods.append("uh")
    if not methods:
        methods = ["gk"]

    df, src_label, err = get_catalog_input(request)
    if err:
        return jsonify(error=err), 400

    cat = df.copy()
    cat["_lat"] = pd.to_numeric(cat[lat_col], errors="coerce")
    cat["_lon"] = pd.to_numeric(cat[lon_col], errors="coerce")
    cat["_mag"] = pd.to_numeric(cat[mag_col], errors="coerce")
    cat["_depth"] = pd.to_numeric(cat.get(depth_col, pd.Series(dtype=float)), errors="coerce")
    try:
        cat["_time"] = pd.to_datetime(cat[time_col])
    except Exception:
        cat["_time"] = pd.to_datetime(cat[time_col], errors="coerce")

    cat = cat.dropna(subset=["_lat", "_lon", "_mag", "_time"]).sort_values("_time").reset_index(drop=True)
    n_input = len(cat)
    if n_input == 0:
        return jsonify(error="No valid rows after parsing"), 400

    # ── Pipeline steps 1–2 before declustering (BBS Sec. 3.3.5, p. 68) ──
    pipeline_notes = []
    try:
        cat, _pre = _apply_pipeline_pre_steps(cat, request.form, pipeline_notes)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    n = len(cat)
    if n == 0:
        return jsonify(error="No valid rows after pipeline steps 1–2"), 400

    # ── Run declustering for each method ──
    method_labels = {"gk": "Gardner & Knopoff (1974)", "gr": "Grünthal", "uh": "Uhrhammer (1986)"}
    results = {}
    for m in methods:
        results[m] = _run_decluster(cat, m)

    # ── Plot 1: Original catalog ──
    fig_orig, ax_orig = plt.subplots(figsize=(10, 8))
    sc = ax_orig.scatter(cat["_lon"], cat["_lat"], s=cat["_mag"] ** 2 * 3,
                         c=cat["_mag"], cmap="YlOrRd", edgecolors="k",
                         linewidths=0.3, alpha=0.7)
    ax_orig.plot(site_lon, site_lat, "b*", markersize=15, label="Site")
    ax_orig.add_patch(plt.Circle((site_lon, site_lat), 300 / 111.32,
                                  fill=False, color="blue", linestyle="--", label="300 km"))
    ax_orig.set_xlabel("Longitude")
    ax_orig.set_ylabel("Latitude")
    ax_orig.set_title(f"Original Catalog ({n} events)")
    ax_orig.legend(loc="upper left")
    ax_orig.set_aspect("equal")
    plt.colorbar(sc, ax=ax_orig, label="Magnitude")
    ax_orig.grid(True, alpha=0.3)

    # ── Window comparison plot ──
    fig_windows = _plot_window_comparison(methods)

    # ── Per-method decluster maps + mag-time scatter ──
    method_plots = {}
    method_magtime = {}
    method_stats = {}
    method_csvs = {}
    for m in methods:
        is_main = results[m]
        n_main = int(is_main.sum())
        n_after = n - n_main
        method_stats[m] = {"mainshocks": n_main, "aftershocks": n_after}

        fig_m = _plot_decluster_map(cat, is_main, site_lat, site_lon,
                                     method_labels[m], m)
        method_plots[m] = fig_to_b64(fig_m)

        fig_mt = _plot_mag_time_scatter(cat, is_main, method_labels[m])
        method_magtime[m] = fig_to_b64(fig_mt)

        out_cols = [c for c in df.columns if c in cat.columns]
        out_cols += [c for c in ("mag_mw", "mag_mw_src") if c in cat.columns]
        method_csvs[m] = cat[is_main][out_cols].to_csv(index=False)

    # ── Time-magnitude comparison plot (overlay) ──
    fig_time = _plot_decluster_time(cat, results)

    # ── 300km filter (use first method for maps/tables) ──
    primary = methods[0]
    cat["is_mainshock"] = results[primary]
    cat["_dist_km"] = cat.apply(
        lambda r: haversine_km(site_lat, site_lon, r["_lat"], r["_lon"]), axis=1)
    within_300 = cat[cat["_dist_km"] <= 300]
    within_300_main = within_300[within_300["is_mainshock"]]

    # ── Map data for Mapbox ──
    map_cols = {"_lat": "lat", "_lon": "lon", "_mag": "mag", "_depth": "depth"}
    map_all = cat[list(map_cols.keys())].fillna(0).rename(columns=map_cols).to_dict("records")
    map_mainshocks = cat[results[primary]][list(map_cols.keys())].fillna(0).rename(
        columns=map_cols).to_dict("records")
    map_300km = within_300_main[list(map_cols.keys())].fillna(0).rename(
        columns=map_cols).to_dict("records")

    # ── Table data ──
    table_display_cols = [c for c in [lat_col, lon_col, mag_col, depth_col, time_col]
                          if c in df.columns]
    table_original = cat[table_display_cols].head(200).fillna("").to_dict("records")

    # ── QAQC summary ──
    qaqc_parts = [f"Source: {src_label}.", f"Input: {n_input} events."]
    qaqc_parts.extend(pipeline_notes)
    qaqc_parts.append(f"Catalog after steps 1–2: {n} events.")
    for m in methods:
        s = method_stats[m]
        qaqc_parts.append(f"Step 3 {method_labels[m]}: {s['mainshocks']} mainshocks, "
                          f"{s['aftershocks']} fore/aftershocks removed.")
    qaqc_parts.append(f"Within 300km ({method_labels[primary]}): "
                      f"{len(within_300_main)} mainshocks")

    # ── Legend counts (focal depth + magnitude bins, unified convention) ──
    depth_classes = depth_class_counts(cat["_depth"])
    mag_bins = {
        "lt4": int((cat["_mag"] < 4.0).sum()),
        "m4": int(((cat["_mag"] >= 4.0) & (cat["_mag"] < 5.0)).sum()),
        "m5": int(((cat["_mag"] >= 5.0) & (cat["_mag"] < 6.0)).sum()),
        "m6": int(((cat["_mag"] >= 6.0) & (cat["_mag"] < 7.0)).sum()),
        "ge7": int((cat["_mag"] >= 7.0).sum()),
    }
    try:
        period_str = f"{cat['_time'].min().year}–{cat['_time'].max().year}"
    except Exception:
        period_str = "—"

    return jsonify(
        plot_original=fig_to_b64(fig_orig),
        plot_windows=fig_to_b64(fig_windows),
        plot_time=fig_to_b64(fig_time),
        method_plots=method_plots,
        method_magtime=method_magtime,
        method_stats=method_stats,
        method_csvs=method_csvs,
        methods_used=methods,
        n_total=n,
        n_input=n_input,
        pipeline_notes=pipeline_notes,
        n_within_300_main=int(len(within_300_main)),
        table_cols=table_display_cols,
        table_original=table_original,
        map_all=map_all,
        map_mainshocks=map_mainshocks,
        map_300km=map_300km,
        depth_classes=depth_classes,
        depth_class_labels=DEPTH_CLASS_LABELS,
        depth_convention_note=DEPTH_CONVENTION_NOTE,
        mag_bins=mag_bins,
        catalog_period=period_str,
        source=src_label,
        qaqc=" ".join(qaqc_parts),
    )


# ── Completeness ──────────────────────────────

def _parse_compl_text(text):
    """Parse 'year,magnitude' lines into sorted list of tuples."""
    pairs = []
    for line in text.strip().split("\n"):
        parts = line.strip().split(",")
        if len(parts) == 2:
            try:
                pairs.append((int(parts[0].strip()), float(parts[1].strip())))
            except ValueError:
                pass
    return sorted(pairs, key=lambda x: x[0])


def _compl_table_to_list(ct):
    """Convert numpy completeness table to list of [year, mag] for JSON."""
    if ct is None:
        return []
    return [[int(r[0]), round(float(r[1]), 1)] for r in ct if not np.isnan(r[0])]


@app.route("/api/completeness", methods=["POST"])
def api_completeness():
    from psha_preprocess.catalogue import stepp_analysis, plot_stepp, plot_mag_time_density

    mag_col = request.form.get("mag_col", "mag")
    time_col = request.form.get("time_col", "time")
    depth_col = request.form.get("depth_col", "depth")
    stepp_mag_bin = float(request.form.get("mag_bin", 1.0))
    stepp_time_bin = float(request.form.get("time_bin", 5.0))
    dens_mag_bin = float(request.form.get("dens_mag_bin", 0.5))
    dens_time_bin = float(request.form.get("dens_time_bin", 5))
    mode = request.form.get("mode", "auto")  # auto, manual, both

    d_shallow = float(request.form.get("d_shallow", 35))
    d_mid = float(request.form.get("d_mid", 70))
    d_deep = float(request.form.get("d_deep", 700))

    manual_tables = {
        "whole": _parse_compl_text(request.form.get("compl_whole", "")),
        "shallow": _parse_compl_text(request.form.get("compl_shallow", "")),
        "mid-depth": _parse_compl_text(request.form.get("compl_mid", "")),
        "deep": _parse_compl_text(request.form.get("compl_deep", "")),
    }

    df, src_label, err = get_catalog_input(request)
    if err:
        return jsonify(error=err), 400

    cat = df.copy()
    cat["_mag"] = pd.to_numeric(cat[mag_col], errors="coerce")
    cat["_depth"] = pd.to_numeric(cat.get(depth_col, pd.Series(dtype=float)), errors="coerce")
    try:
        cat["_time"] = pd.to_datetime(cat[time_col], utc=True)
        cat["_year"] = cat["_time"].dt.year + cat["_time"].dt.dayofyear / 365.25
    except Exception:
        cat["_year"] = pd.to_numeric(cat[time_col], errors="coerce")

    cat = cat.dropna(subset=["_mag", "_year"])

    def classify(d):
        if pd.isna(d):
            return None
        if 0 <= d < d_shallow:
            return "shallow"
        if d_shallow <= d < d_mid:
            return "mid-depth"
        if d_mid <= d < d_deep:
            return "deep"
        return None

    cat["_depth_class"] = cat["_depth"].apply(classify)

    depth_labels = {
        "whole": "Whole Catalogue",
        "shallow": f"Shallow (0-{int(d_shallow)} km)",
        "mid-depth": f"Mid-depth ({int(d_shallow)}-{int(d_mid)} km)",
        "deep": f"Deep ({int(d_mid)}-{int(d_deep)} km)",
    }

    subsets = {"whole": cat}
    for dc in ["shallow", "mid-depth", "deep"]:
        s = cat[cat["_depth_class"] == dc]
        if len(s) > 0:
            subsets[dc] = s

    depth_counts = {k: len(v) for k, v in subsets.items()}

    output_sections = []
    for key, subset in subsets.items():
        label = depth_labels[key]
        years = subset["_year"].values
        mags = subset["_mag"].values
        n = len(subset)

        section = {"key": key, "label": label, "count": n, "plots": [],
                   "auto_table": [], "manual_table": []}

        auto_ct = None
        if mode in ("auto", "both") and n >= 10:
            try:
                result = stepp_analysis(years, mags, stepp_mag_bin, stepp_time_bin)
                if result is not None:
                    auto_ct = result["completeness_table"]
                    section["auto_table"] = _compl_table_to_list(auto_ct)

                    fig_stepp = plot_stepp(result, title=label)
                    section["plots"].append({
                        "title": f"Stepp (1972) – {label}",
                        "plot": fig_to_b64(fig_stepp),
                    })
            except Exception as e:
                section["stepp_error"] = str(e)

        manual_ct = None
        if mode in ("manual", "both"):
            m_pairs = manual_tables.get(key, [])
            if m_pairs:
                manual_ct = np.array(m_pairs)
                section["manual_table"] = [[int(y), float(m)] for y, m in m_pairs]

        if n >= 5:
            overlay_ct = None
            if mode == "auto" and auto_ct is not None:
                overlay_ct = auto_ct
            elif mode == "manual" and manual_ct is not None:
                overlay_ct = manual_ct
            elif mode == "both":
                overlay_ct = auto_ct  # auto as primary

            fig_dens = plot_mag_time_density(
                years, mags, dens_mag_bin, dens_time_bin,
                completeness_table=overlay_ct, title=label)

            if mode == "both" and manual_ct is not None:
                from psha_preprocess.catalogue.completeness import _build_step_curve
                ax = fig_dens.axes[0]
                sx, sy = _build_step_curve(manual_ct, years.min(), years.max(),
                                           dens_time_bin)
                ax.plot(sx, sy, "w--", linewidth=2, label="Manual")
                ax.legend(fontsize=8)

            section["plots"].append({
                "title": f"Magnitude-Time Density – {label}",
                "plot": fig_to_b64(fig_dens),
            })

        output_sections.append(section)

    qaqc_parts = [f"Source: {src_label}.", f"Completeness: {len(cat)} events, mode={mode}."]
    for s in output_sections:
        qaqc_parts.append(f"{s['label']}: {s['count']} events")
        if s["auto_table"]:
            qaqc_parts.append(f"  Auto: {len(s['auto_table'])} bins")

    return jsonify(
        sections=output_sections,
        total_events=len(cat),
        depth_counts=depth_counts,
        mode=mode,
        source=src_label,
        qaqc=" ".join(qaqc_parts),
    )


# ── Gutenberg-Richter ─────────────────────────
@app.route("/api/gutenberg_richter", methods=["POST"])
def api_gutenberg_richter():
    mag_col = request.form.get("mag_col", "mag")
    time_col = request.form.get("time_col", "time")
    lat_col = request.form.get("lat_col", "latitude")
    lon_col = request.form.get("lon_col", "longitude")
    dm = float(request.form.get("dm", 0.1))
    Mc = float(request.form.get("mc", 4.45))
    M_LIMIT = float(request.form.get("m_limit", 5.0))
    M_MAX = float(request.form.get("m_max", 8.0))
    compl_pairs = _parse_compl_text(request.form.get("compl_whole", ""))

    df, src_label, err = get_catalog_input(request)
    if err:
        return jsonify(error=err), 400

    cat = df.copy()
    cat["_mag"] = pd.to_numeric(cat[mag_col], errors="coerce")
    if lat_col in cat.columns and lon_col in cat.columns:
        cat["_lat"] = pd.to_numeric(cat[lat_col], errors="coerce")
        cat["_lon"] = pd.to_numeric(cat[lon_col], errors="coerce")
    parsed = to_datetime_safe(cat[time_col])
    if parsed.notna().any():
        cat["_time"] = parsed
        cat["_year"] = parsed.dt.year + parsed.dt.dayofyear / 365.25
    else:
        cat["_year"] = pd.to_numeric(cat[time_col], errors="coerce")

    cat = cat.dropna(subset=["_mag", "_year"])
    n_input = len(cat)
    if n_input == 0:
        return jsonify(error="No valid rows after parsing"), 400

    # ── Pipeline steps 1–3 before rate fitting (BBS Sec. 3.3.5, p. 68) ──
    notes, warnings = [], []
    try:
        cat, pre_info = _apply_pipeline_pre_steps(cat, request.form, notes)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    cat, declustered = _maybe_decluster_first(cat, request.form, notes)
    if not declustered:
        warnings.append(
            "Input was not declustered here — GR rate estimation assumes a "
            "declustered (Poisson) catalogue (BBS pp. 68, 92). Upload a "
            "declustered CSV or tick 'Decluster first (GK)'.")

    T = float(cat["_year"].max() - cat["_year"].min())
    if not np.isfinite(T) or T <= 0:
        return jsonify(error="Catalog duration is zero"), 400

    mags = cat["_mag"].values
    years = cat["_year"].values
    end_year = float(cat["_year"].max())

    mmin = np.floor(mags.min() / dm) * dm
    edges = np.arange(mmin, M_MAX + dm, dm)
    m_centers = edges[:-1] + dm / 2.0

    if compl_pairs:
        # Events counted only inside their bin's period of completeness
        # (BBS Fig. 3.10 p. 78; Completeness Levels pp. 71–72).
        inc_rates = pl.completeness_rates(mags, years, compl_pairs, edges, end_year)
        notes.append(f"Rates: completeness-corrected, {len(compl_pairs)} levels "
                     "(BBS Fig. 3.10, p. 78).")
    else:
        inc_counts, _ = np.histogram(mags, bins=edges)
        inc_rates = inc_counts / T
        warnings.append(
            "No completeness table supplied — rates assume the catalogue is "
            "uniformly complete over its whole span (BBS pp. 71–72).")
    cum_rates = inc_rates[::-1].cumsum()[::-1]

    # b-value: Aki MLE (Lamessa et al., Eq. 21), error per Shi & Bolt (Eq. 22).
    # The sample is restricted to the period where M >= Mc is complete so the
    # MLE's uniform-completeness premise holds.
    if compl_pairs:
        cy = pl.completeness_year_for(compl_pairs, Mc)
        if cy is None:
            return jsonify(error=f"Mc={Mc} is below the lowest completeness level"), 400
        fit_mask = (mags >= Mc) & (years >= cy)
        notes.append(f"b-value sample: M>={Mc} from {int(cy)} on "
                     f"({int(fit_mask.sum())} events).")
    else:
        fit_mask = mags >= Mc
    m_fit = mags[fit_mask]
    if len(m_fit) < 5:
        return jsonify(error="Not enough events above Mc"), 400

    bin_corr = request.form.get("bin_correction", "0") == "1"
    b_value, b_stderr = pl.b_value_aki(m_fit, Mc, dm=dm if bin_corr else 0.0)
    if not np.isfinite(b_value):
        return jsonify(error="b-value could not be estimated from the sample"), 400
    if bin_corr:
        notes.append("b-value: Aki MLE with dm/2 binning correction — the "
                     "correction has no basis in the Reference Folder.")
    else:
        notes.append("b-value: Aki MLE without binning correction "
                     "(Lamessa et al., Eqs. 21–22).")

    idx_ref = np.where(m_centers >= Mc)[0][0]
    Nref = cum_rates[idx_ref]
    a_value = np.log10(Nref) + b_value * m_centers[idx_ref] if Nref > 0 else 0

    m_grid = np.linspace(M_LIMIT, M_MAX, 600)
    model_cum = 10 ** (a_value - b_value * m_grid)

    cum_at_centers = 10 ** (a_value - b_value * m_centers)
    cum_at_next = 10 ** (a_value - b_value * (m_centers + dm))
    model_inc = np.maximum(cum_at_centers - cum_at_next, 1e-20)

    mask = (m_centers >= M_LIMIT) & (m_centers <= M_MAX)
    obs_inc_mask = mask & (inc_rates > 0)
    obs_cum_mask = mask & (cum_rates > 0)

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.semilogy(m_centers[obs_inc_mask], inc_rates[obs_inc_mask], "o", markersize=6,
                label="Observed Incremental Rate")
    ax.semilogy(m_centers[mask], model_inc[mask], "-", linewidth=1.5,
                label="Model Incremental Rate")
    ax.semilogy(m_centers[obs_cum_mask], cum_rates[obs_cum_mask], "s", markersize=6,
                label="Observed Cumulative Rate")
    ax.semilogy(m_grid, model_cum, "-", linewidth=2,
                label="Model Cumulative Rate")

    ax.set_xlabel("Magnitude", fontsize=12)
    ax.set_ylabel("Annual Occurrence Rate", fontsize=12)
    ax.set_title("Gutenberg–Richter Recurrence Plot", fontsize=13)
    ax.legend(fontsize=9)
    ax.grid(True, which="both", linestyle="--", linewidth=0.5)
    ax.set_xlim(M_LIMIT, M_MAX)

    dur_line = "T varies by completeness level" if compl_pairs else f"T = {int(T)} years"
    eq_text = (
        r"$\log_{10}N(M \geq m) = a - bM$" "\n"
        f"a = {a_value:.3f}\n"
        f"b = {b_value:.3f} ± {b_stderr:.3f}\n"
        f"{dur_line}"
    )
    ax.text(0.02, 0.02, eq_text, transform=ax.transAxes, fontsize=10,
            verticalalignment="bottom",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    rates_csv = pd.DataFrame({
        "Magnitude": m_centers[mask],
        "Cum_Rate": cum_rates[mask],
        "Inc_Rate": inc_rates[mask],
    }).to_csv(index=False)

    qaqc_parts = [f"Source: {src_label}.", f"Input: {n_input} events."]
    qaqc_parts.extend(notes)
    qaqc_parts.extend(f"WARNING: {w}" for w in warnings)
    qaqc_parts.append(f"GR: a={a_value:.4f}, b={b_value:.4f}±{b_stderr:.4f}, "
                      f"Mc={Mc}, N(fit)={len(m_fit)}")

    return jsonify(
        plot=fig_to_b64(fig),
        a_value=round(a_value, 4),
        b_value=round(b_value, 4),
        b_stderr=round(float(b_stderr), 4),
        duration=round(T, 1),
        n_events=int(len(m_fit)),
        n_input=n_input,
        completeness_used=bool(compl_pairs),
        pipeline_notes=notes,
        warnings=warnings,
        rates_csv=rates_csv,
        source=src_label,
        qaqc=" ".join(qaqc_parts),
    )


# ── MFD (Magnitude-Frequency Distribution) ────
@app.route("/api/mfd", methods=["POST"])
def api_mfd():
    mag_col = request.form.get("mag_col", "mag")
    time_col = request.form.get("time_col", "time")
    depth_col = request.form.get("depth_col", "depth")
    lat_col = request.form.get("lat_col", "latitude")
    lon_col = request.form.get("lon_col", "longitude")
    dm = float(request.form.get("dm", 0.1))
    min_mag = float(request.form.get("min_mag", 4.5))
    max_mag = float(request.form.get("max_mag", 8.0))

    compl_texts = {
        "shallow": request.form.get("compl_shallow", ""),
        "intermediate": request.form.get("compl_mid", ""),
        "deep": request.form.get("compl_deep", ""),
    }
    compl_tables = {k: _parse_compl_text(v) for k, v in compl_texts.items()}

    df, src_label, err = get_catalog_input(request)
    if err:
        return jsonify(error=err), 400

    cat = df.copy()
    cat["_mag"] = pd.to_numeric(cat[mag_col], errors="coerce")
    cat["_depth"] = pd.to_numeric(cat[depth_col], errors="coerce")
    if lat_col in cat.columns and lon_col in cat.columns:
        cat["_lat"] = pd.to_numeric(cat[lat_col], errors="coerce")
        cat["_lon"] = pd.to_numeric(cat[lon_col], errors="coerce")
    parsed = to_datetime_safe(cat[time_col])
    if parsed.notna().any():
        cat["_time"] = parsed
        cat["_year"] = parsed.dt.year
    else:
        cat["_year"] = pd.to_numeric(cat[time_col], errors="coerce")

    cat = cat.dropna(subset=["_mag", "_year", "_depth"])
    n_input = len(cat)
    if n_input == 0:
        return jsonify(error="No valid rows after parsing"), 400

    # ── Pipeline steps 1–3 before rate fitting (BBS Sec. 3.3.5, p. 68) ──
    notes, warnings = [], []
    try:
        cat, pre_info = _apply_pipeline_pre_steps(cat, request.form, notes)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    cat, declustered = _maybe_decluster_first(cat, request.form, notes)
    if not declustered:
        warnings.append(
            "Input was not declustered here — MFD rates assume a declustered "
            "(Poisson) catalogue (BBS pp. 68, 92). Upload a declustered CSV "
            "or tick 'Decluster first (GK)'.")

    cat = cat[cat["_mag"] >= min_mag]
    if cat.empty:
        return jsonify(error="No events at or above min_mag"), 400

    year_min = int(cat["_year"].min())
    year_max = int(cat["_year"].max())
    T_total = max(year_max - year_min, 1)

    # Unified focal-depth convention (CODE_REVIEW A6) — same classes on the
    # Catalog, Declustering and Completeness (defaults) pages.
    s0, s1, s2 = DEPTH_BOUNDS_KM

    def classify_depth(d):
        if 0 <= d < s0:
            return "shallow"
        if s0 <= d < s1:
            return "intermediate"
        if s1 <= d < s2:
            return "deep"
        return None

    cat["_depth_class"] = cat["_depth"].apply(classify_depth)
    cat = cat.dropna(subset=["_depth_class"])

    depth_labels = DEPTH_CLASS_LABELS

    edges = np.arange(min_mag, max_mag + dm, dm)
    m_centers = edges[:-1] + dm / 2.0

    depth_plots = []
    oq_arbitrary = []
    all_rates = {}

    for dkey in ["shallow", "intermediate", "deep"]:
        label = depth_labels[dkey]
        subset = cat[cat["_depth_class"] == dkey]
        n = len(subset)
        if subset.empty:
            continue

        mags = subset["_mag"].values
        years = subset["_year"].values
        compl_pairs = compl_tables.get(dkey, [])
        if not compl_pairs:
            # No table for this class: assume completeness over the whole
            # span, stated explicitly so the assumption reaches the QA/QC log.
            compl_pairs = [[year_min, min_mag]]
            warnings.append(
                f"{label}: no completeness table — rates assume uniform "
                f"completeness from {year_min} (BBS pp. 71–72).")

        # A2 fix: an event is counted ONLY if it occurred on or after the
        # completeness year of its magnitude bin, and the count is divided
        # by that bin's complete duration (BBS Fig. 3.10 p. 78; pp. 71–72).
        inc_rates = pl.completeness_rates(mags, years, compl_pairs, edges,
                                          float(year_max))
        cum_rates = inc_rates[::-1].cumsum()[::-1]

        all_rates[dkey] = {
            "inc_rates": inc_rates,
            "cum_rates": cum_rates,
            "count": n,
        }

        # b-value sample restricted to the period where M >= min_mag is
        # complete, so the Aki MLE premise holds (Lamessa et al., Eq. 21).
        cy_fit = pl.completeness_year_for(compl_pairs, min_mag + dm / 2.0)
        if cy_fit is None:
            cy_fit = year_min
        m_fit = mags[(mags >= min_mag) & (years >= cy_fit)]
        if len(m_fit) >= 5:
            b_val, b_err = pl.b_value_aki(m_fit, min_mag)
            if not np.isfinite(b_val):
                b_val, b_err = 0.0, 0.0
            idx_ref = 0
            Nref = cum_rates[idx_ref]
            a_val = np.log10(max(Nref, 1e-20)) + b_val * m_centers[idx_ref]
            m_grid = np.linspace(min_mag, max_mag, 300)
            model_cum = 10 ** (a_val - b_val * m_grid)
        else:
            a_val, b_val, b_err = 0, 0, 0
            m_grid, model_cum = np.array([]), np.array([])

        fig, ax = plt.subplots(figsize=(10, 6))
        mask = inc_rates > 0
        if mask.any():
            ax.semilogy(m_centers[mask], inc_rates[mask], "o", markersize=6,
                        label="Observed Incremental")
        mask_c = cum_rates > 0
        if mask_c.any():
            ax.semilogy(m_centers[mask_c], cum_rates[mask_c], "s", markersize=6,
                        label="Observed Cumulative")
        if len(m_grid) > 0:
            ax.semilogy(m_grid, model_cum, "-", linewidth=2,
                        label=f"GR Model (a={a_val:.2f}, b={b_val:.2f})")

        ax.set_xlabel("Magnitude", fontsize=12)
        ax.set_ylabel("Annual Occurrence Rate", fontsize=12)
        ax.set_title(f"MFD – {label} (n={n})", fontsize=13)
        ax.legend(fontsize=9)
        ax.grid(True, which="both", linestyle="--", linewidth=0.5)
        ax.set_xlim(min_mag, max_mag)

        if len(m_fit) >= 5:
            eq_text = (
                r"$\log_{10}N(M \geq m) = a - bM$" "\n"
                f"a = {a_val:.3f}\nb = {b_val:.3f} ± {b_err:.3f}\n"
                "T_eff varies by bin"
            )
            ax.text(0.02, 0.02, eq_text, transform=ax.transAxes, fontsize=9,
                    verticalalignment="bottom",
                    bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

        fig.tight_layout()
        depth_plots.append({
            "label": label,
            "plot": fig_to_b64(fig),
            "count": n,
        })

        nonzero = inc_rates > 0
        if nonzero.any():
            arb_mags = m_centers[nonzero]
            arb_rates = inc_rates[nonzero]
            xml_lines = [f"<!-- {label} -->"]
            xml_lines.append("<arbitraryMFD>")
            xml_lines.append("  <occurRates>" +
                             " ".join(f"{r:.6e}" for r in arb_rates) +
                             "</occurRates>")
            xml_lines.append("  <magnitudes>" +
                             " ".join(f"{m:.2f}" for m in arb_mags) +
                             "</magnitudes>")
            xml_lines.append("</arbitraryMFD>")
            oq_arbitrary.append({
                "label": label,
                "xml": "\n".join(xml_lines),
            })

    # ── Combined MFD plot (all depth classes) ──
    fig, ax = plt.subplots(figsize=(10, 7))
    colors = {"shallow": "#1f77b4", "intermediate": "#ff7f0e", "deep": "#2ca02c"}
    for dkey in ["shallow", "intermediate", "deep"]:
        if dkey not in all_rates:
            continue
        r = all_rates[dkey]
        label = depth_labels[dkey]
        c = colors[dkey]
        mask_c = r["cum_rates"] > 0
        mask_i = r["inc_rates"] > 0
        if mask_c.any():
            ax.semilogy(m_centers[mask_c], r["cum_rates"][mask_c], "s",
                        color=c, markersize=6, label=f"{label} cumulative")
        if mask_i.any():
            ax.semilogy(m_centers[mask_i], r["inc_rates"][mask_i], "o",
                        color=c, markersize=4, alpha=0.6,
                        label=f"{label} incremental")

    ax.set_xlabel("Magnitude", fontsize=12)
    ax.set_ylabel("Annual Occurrence Rate", fontsize=12)
    ax.set_title("Completeness-Corrected MFD by Depth Class", fontsize=13)
    ax.legend(fontsize=8, ncol=2)
    ax.grid(True, which="both", linestyle="--", linewidth=0.5)
    ax.set_xlim(min_mag, max_mag)

    fig.tight_layout()
    combined_plot = fig_to_b64(fig)

    # ── Overall GR fit (all classes combined) ──
    all_mags = cat["_mag"].values
    m_fit_all = all_mags[all_mags >= min_mag]
    if len(m_fit_all) >= 5:
        b_all, b_all_err = pl.b_value_aki(m_fit_all, min_mag)
        if not np.isfinite(b_all):
            b_all, b_all_err = 0.0, 0.0
        inc_all, _ = np.histogram(all_mags, bins=edges)
        cum_all = inc_all[::-1].cumsum()[::-1]
        cum_rate_all = cum_all / T_total
        Nref_all = cum_rate_all[0]
        a_all = np.log10(max(Nref_all, 1e-20)) + b_all * m_centers[0]
        warnings.append(
            f"Combined TruncatedGR fit uses the whole-span duration "
            f"(T={T_total} yr) with no per-class completeness correction.")
    else:
        a_all, b_all, b_all_err = 0, 0, 0

    truncgr_xml = (
        "<truncGutenbergRichterMFD\n"
        f'  aValue="{a_all:.4f}"\n'
        f'  bValue="{b_all:.4f}"\n'
        f'  minMag="{min_mag:.1f}"\n'
        f'  maxMag="{max_mag:.1f}"\n'
        f'  binWidth="{dm}"/>'
    )

    csv_rows = [["magnitude", "depth_class", "inc_rate", "cum_rate"]]
    for dkey in ["shallow", "intermediate", "deep"]:
        if dkey not in all_rates:
            continue
        r = all_rates[dkey]
        for i, mc in enumerate(m_centers):
            csv_rows.append([f"{mc:.2f}", dkey,
                             f"{r['inc_rates'][i]:.6e}",
                             f"{r['cum_rates'][i]:.6e}"])
    rates_csv = "\n".join(",".join(row) for row in csv_rows)

    oq_xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                    "<!-- MFD Output for OpenQuake -->", ""]
    oq_xml_parts.append("<!-- TruncatedGRMFD (combined) -->")
    oq_xml_parts.append(truncgr_xml)
    oq_xml_parts.append("")
    for item in oq_arbitrary:
        oq_xml_parts.append(item["xml"])
        oq_xml_parts.append("")
    oq_xml = "\n".join(oq_xml_parts)

    qaqc_parts = [f"Source: {src_label}.", f"Input: {n_input} events."]
    qaqc_parts.extend(notes)
    qaqc_parts.extend(f"WARNING: {w}" for w in warnings)
    qaqc_parts.append(DEPTH_CONVENTION_NOTE)
    qaqc_parts.append(f"MFD: {len(cat)} events, dm={dm}, "
                      f"a={a_all:.4f}, b={b_all:.4f}±{b_all_err:.4f}, T={T_total}yr")

    return jsonify(
        plot=combined_plot,
        depth_plots=depth_plots,
        total_events=len(cat),
        n_input=n_input,
        a_value=round(a_all, 4),
        b_value=round(b_all, 4),
        b_stderr=round(float(b_all_err), 4),
        duration=T_total,
        pipeline_notes=notes,
        warnings=warnings,
        depth_class_labels=DEPTH_CLASS_LABELS,
        depth_convention_note=DEPTH_CONVENTION_NOTE,
        oq_arbitrary=oq_arbitrary,
        oq_truncated_gr=truncgr_xml,
        oq_xml=oq_xml,
        rates_csv=rates_csv,
        source=src_label,
        qaqc=" ".join(qaqc_parts),
    )


# ─────────────────────────────────────────────
# Max Magnitude
# ─────────────────────────────────────────────
@app.route("/api/max_magnitude", methods=["POST"])
def api_max_magnitude():
    mag_col = request.form.get("mag_col", "mag")
    time_col = request.form.get("time_col", "time")
    lat_col = request.form.get("lat_col", "latitude")
    lon_col = request.form.get("lon_col", "longitude")
    m_min = float(request.form.get("m_min", 4.5))
    b_form = request.form.get("b_value", "").strip()

    df, src_label, err = get_catalog_input(request)
    if err:
        return jsonify(error=err), 400
    if mag_col not in df.columns or time_col not in df.columns:
        return jsonify(error=f"Columns '{mag_col}'/'{time_col}' not found"), 400

    # B1 fix: one frame, drop rows where either magnitude or time is invalid,
    # sort by time — years and magnitudes stay aligned.
    cat = df.copy()
    cat["_mag"] = pd.to_numeric(cat[mag_col], errors="coerce")
    if lat_col in cat.columns and lon_col in cat.columns:
        cat["_lat"] = pd.to_numeric(cat[lat_col], errors="coerce")
        cat["_lon"] = pd.to_numeric(cat[lon_col], errors="coerce")
    parsed = to_datetime_safe(cat[time_col])
    if parsed.notna().any():
        cat["_time"] = parsed
        cat["_year"] = parsed.dt.year + parsed.dt.dayofyear / 365.25
    else:
        cat["_year"] = pd.to_numeric(cat[time_col], errors="coerce")
    cat = cat.dropna(subset=["_mag", "_year"]).sort_values("_year").reset_index(drop=True)
    n_input = len(cat)
    if n_input == 0:
        return jsonify(error="No valid rows after parsing"), 400

    # ── Pipeline steps 1–2 (BBS Sec. 3.3.5, p. 68) ──
    notes, warnings = [], []
    try:
        cat, pre_info = _apply_pipeline_pre_steps(cat, request.form, notes)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    cat, declustered = _maybe_decluster_first(cat, request.form, notes)
    if not declustered:
        warnings.append(
            "Input was not declustered here — the Kijko–Sellevoll estimator "
            "assumes a declustered catalogue complete above Mmin "
            "(BBS p. 92; kijko2004.pdf).")

    mag = cat["_mag"]
    m_max_obs = float(mag.max())
    m_sample = mag[mag >= m_min]
    n_above = int(len(m_sample))
    if n_above < 2:
        return jsonify(error=f"Fewer than 2 events at or above Mmin={m_min}"), 400
    if m_max_obs < m_min:
        return jsonify(error=f"Observed maximum {m_max_obs} is below Mmin={m_min}"), 400

    # b-value: user-supplied, else Aki MLE on M >= Mmin (Lamessa et al., Eq. 21).
    b_stderr = None
    if b_form:
        try:
            b_used = float(b_form)
        except ValueError:
            return jsonify(error=f"Invalid b-value '{b_form}'"), 400
        if b_used <= 0:
            return jsonify(error="b-value must be > 0"), 400
        b_source = "user"
        notes.append(f"b = {b_used:.3f} supplied by user.")
    else:
        b_used, b_stderr = pl.b_value_aki(m_sample.values, m_min)
        if not np.isfinite(b_used):
            return jsonify(error="b-value could not be estimated; supply one"), 400
        b_source = "Aki MLE"
        notes.append(
            f"b = {b_used:.3f} ± {b_stderr:.3f} from Aki MLE on M>={m_min} "
            "(Lamessa et al., Eqs. 21–22); assumes completeness above Mmin "
            "over the whole span.")

    # A3 fix: Kijko–Sellevoll statistical Mmax (kijko2004.pdf, Eqs. 6–8,
    # pp. 1659–1660) replaces the uncited flat 'observed + 0.5'.
    mmax_ks = pl.kijko_sellevoll_mmax(m_max_obs, n_above, b_used, m_min)

    fig_sc, ax_sc = plt.subplots(figsize=(10, 5))
    ax_sc.plot(cat["_year"].values, cat["_mag"].values, "o", markersize=3,
               alpha=0.5, color="#3b82f6")
    ax_sc.axhline(m_min, color="#ef4444", linestyle="--", linewidth=1,
                  label=f"Mmin = {m_min}")
    ax_sc.set_xlabel("Year")
    ax_sc.set_ylabel("Magnitude")
    ax_sc.set_title(f"Magnitude-Time Distribution ({len(cat)} events)")
    ax_sc.legend(fontsize=8)
    ax_sc.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()
    plot_scatter = fig_to_b64(fig_sc)

    # Cumulative moment release. M0 = 10^(1.5*Mw + 9.05) N·m is defined for
    # MOMENT magnitude only (Hanks & Kanamori 1979, Eq. 7, p. 2349; BBS
    # Eq. 2.5, pp. 35, 57), so each event is first aligned to Mw: reported
    # Mw > Ms->Mw > mb->Mw (Lamessa 2019 p. 5: Scordilis 2006 Eqs. 1/8);
    # events with no convertible scale pass through flagged (BBS p. 69).
    def _scale_col(name):
        col = request.form.get(f"{name}_col", name)
        if col in cat.columns:
            vals = pd.to_numeric(cat[col], errors="coerce")
            return vals.values if vals.notna().any() else None
        return None

    if "mag_mw" in cat.columns:        # step 1 already aligned _mag to Mw
        mw_moment = cat["_mag"].values
        if "mag_mw_src" in cat.columns:   # recount on the events actually summed
            moment_sources = {str(k): int(v) for k, v in
                              cat["mag_mw_src"].value_counts().items()}
        else:
            moment_sources = pre_info.get("mw_sources") or {
                "harmonized": int(len(cat))}
        notes.append("Moment input: step-1 Mw magnitudes used directly "
                     "(Hanks–Kanamori Eq. 7 p. 2349; BBS Eq. 2.5 pp. 35, 57).")
    else:
        # Step 1 was disabled or skipped: align to Mw for the moment sum
        # only, with the same cited, range-gated relations.
        ms_v, mb_v = _scale_col("ms"), _scale_col("mb")
        mw_moment, msrc = pl.homogenize_to_mw(
            mw=_scale_col("mw"), ms=ms_v, mb=mb_v,
            fallback=cat["_mag"].values)
        labels, counts = np.unique(msrc, return_counts=True)
        moment_sources = {str(l): int(c) for l, c in zip(labels, counts)}
        notes.append("Moment input aligned to Mw per event: "
                     + _mw_breakdown(moment_sources)
                     + " (Hanks–Kanamori Eq. 7 p. 2349; Lamessa p. 5, "
                       "Scordilis 2006 Eqs. 1/8, applied inside their "
                       "validity ranges only).")
        if moment_sources.get("raw"):
            warnings.append(
                f"{moment_sources['raw']} event(s) enter the moment sum on "
                "their reported scale (Ms/mb outside the relations' ranges, "
                "or Ml-only — no folder-backed Ml→Mw relation).")

    moment = pl.seismic_moment_nm(mw_moment)
    cum_moment = np.cumsum(moment)

    # Per-event source labels for the clickable catalogue table.
    if "mag_mw_src" in cat.columns:
        src_arr = cat["mag_mw_src"].astype(str).values
    elif "mag_mw" in cat.columns:
        src_arr = np.full(len(cat), "harmonized", dtype=object)
    else:
        src_arr = msrc

    events_detail, moment_relations = _events_detail_payload(
        cat, mag_col, request.form, src_arr, mw_moment, moment)

    fig_cm, ax_cm = plt.subplots(figsize=(10, 5))
    # Step curve: moment accumulates instantaneously at each event time.
    ax_cm.plot(cat["_year"].values, cum_moment, "b-", linewidth=1.5,
               drawstyle="steps-post")
    ax_cm.set_xlabel("Year")
    ax_cm.set_ylabel("Cumulative Seismic Moment (N.m)")
    ax_cm.set_title("Cumulative Moment Release (Mw-aligned)")
    src_text = ", ".join(f"{v} {k}" for k, v in sorted(moment_sources.items()))
    ax_cm.text(0.98, 0.02, f"M0 = 10^(1.5·Mw + 9.05) N·m\nMw basis: {src_text}",
               transform=ax_cm.transAxes, fontsize=8, ha="right", va="bottom",
               bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))
    ax_cm.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()
    plot_moment = fig_to_b64(fig_cm)

    results = {
        "observed_mmax": round(m_max_obs, 2),
        "mmax_kijko_sellevoll": round(mmax_ks, 2),
        "ks_increment": round(mmax_ks - m_max_obs, 2),
        "b_used": round(float(b_used), 3),
        "b_source": b_source,
        "b_stderr": round(float(b_stderr), 3) if b_stderr is not None else None,
        "m_min": m_min,
        "n_above_mmin": n_above,
        "n_events": int(len(mag)),
        "mag_range": f"{mag.min():.1f} - {mag.max():.1f}",
    }

    qaqc_parts = [f"Source: {src_label}.", f"Input: {n_input} events."]
    qaqc_parts.extend(notes)
    qaqc_parts.extend(f"WARNING: {w}" for w in warnings)
    qaqc_parts.append(
        f"Mmax: observed={m_max_obs:.2f}, Kijko–Sellevoll={mmax_ks:.2f} "
        f"(kijko2004.pdf Eqs. 6–8), n(M>={m_min})={n_above}, b={b_used:.3f}")

    return jsonify(
        plot_scatter=plot_scatter,
        plot_moment=plot_moment,
        results=results,
        moment_sources=moment_sources,
        events_detail=events_detail,
        moment_relations=moment_relations,
        pipeline_notes=notes,
        warnings=warnings,
        source=src_label,
        qaqc=" ".join(qaqc_parts),
    )


if __name__ == "__main__":
    # Werkzeug debugger is an RCE vector (CODE_REVIEW C2): opt in via env var
    # for local development only; never with a non-loopback bind address.
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", use_reloader=False,
            host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
