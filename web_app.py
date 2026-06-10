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

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = None
app.config["MAX_FORM_MEMORY_SIZE"] = None
app.config["MAX_FORM_PARTS"] = None

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
    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(io.BytesIO(raw), sep=sep)
            if df.shape[1] >= 2:
                return df
        except Exception:
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


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat, dlon = rlat2 - rlat1, rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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
    depths = np.array([ev["depth_km"] for ev in events if ev["depth_km"] is not None], dtype=float)
    mag_bins = {
        "lt4": int((mags < 4.0).sum()),
        "m4": int(((mags >= 4.0) & (mags < 5.0)).sum()),
        "m5": int(((mags >= 5.0) & (mags < 6.0)).sum()),
        "m6": int(((mags >= 6.0) & (mags < 7.0)).sum()),
        "ge7": int((mags >= 7.0).sum()),
    }
    depth_classes = {
        "shallow": int((depths < 70).sum()),
        "intermediate": int(((depths >= 70) & (depths < 300)).sum()),
        "deep": int((depths >= 300).sum()),
        "unknown": int(len(events) - len(depths)),
    }

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
        n_total=meta["total_events"],
        n_excluded_from_analysis=n_no_dt,
        audit=audit,
    )


# ── Declustering ──────────────────────────────
def _decluster_window_calc(mags_arr, method):
    """Compute space (km) and time (days) windows for given magnitudes."""
    M = np.asarray(mags_arr, dtype=float)
    DAYS = 364.75
    if method == "gk":
        sw_space = np.power(10.0, 0.1238 * M + 0.983)
        sw_time = np.power(10.0, 0.032 * M + 2.7389) / DAYS
        sw_time[M < 6.5] = np.power(10.0, 0.5409 * M[M < 6.5] - 0.547) / DAYS
    elif method == "gr":
        sw_space = np.exp(1.77 + np.sqrt(0.037 + 1.02 * M))
        sw_time = np.abs(np.exp(-3.95 + np.sqrt(0.62 + 17.32 * M))) / DAYS
        sw_time[M >= 6.5] = np.power(10.0, 2.8 + 0.024 * M[M >= 6.5]) / DAYS
    elif method == "uh":
        sw_space = np.exp(-1.024 + 0.804 * M)
        sw_time = np.exp(-2.87 + 1.235 * M) / DAYS
    else:
        raise ValueError(f"Unknown method: {method}")
    return sw_space, sw_time  # km, fractional years


def _run_decluster(cat, method):
    """Run Gardner-Knopoff declustering with specified window method.

    Returns boolean array (True = mainshock).
    """
    n = len(cat)
    lats = cat["_lat"].values
    lons = cat["_lon"].values
    mags = cat["_mag"].values
    times = cat["_time"].values

    sw_space, sw_time_yr = _decluster_window_calc(mags, method)
    sw_time_days = sw_time_yr * 364.75

    is_main = np.ones(n, dtype=bool)
    for i in range(n):
        if not is_main[i]:
            continue
        t_win_td = np.timedelta64(int(sw_time_days[i]), "D")
        for j in range(i + 1, n):
            if not is_main[j]:
                continue
            if times[j] - times[i] > t_win_td:
                break
            if haversine_km(lats[i], lons[i], lats[j], lons[j]) <= sw_space[i]:
                is_main[j] = False
    return is_main


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


def _plot_decluster_time(cat, results, time_col):
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
    DAYS = 364.75

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    for m in methods:
        sw_space, sw_time_yr = _decluster_window_calc(mags, m)
        sw_time_days = sw_time_yr * DAYS
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
    n = len(cat)
    if n == 0:
        return jsonify(error="No valid rows after parsing"), 400

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

        out_cols = [c for c in df.columns]
        method_csvs[m] = cat[is_main][out_cols].to_csv(index=False)

    # ── Time-magnitude comparison plot (overlay) ──
    fig_time = _plot_decluster_time(cat, results, time_col)

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
    qaqc_parts = [f"Source: {src_label}.", f"Catalog: {n} events."]
    for m in methods:
        s = method_stats[m]
        qaqc_parts.append(f"{method_labels[m]}: {s['mainshocks']} mainshocks, "
                          f"{s['aftershocks']} aftershocks removed.")
    qaqc_parts.append(f"Within 300km ({method_labels[primary]}): "
                      f"{len(within_300_main)} mainshocks")

    # ── Legend counts (focal depth + magnitude bins) ──
    # Focal-depth classes per USGS convention:
    #   shallow 0–70 km, intermediate 70–300 km, deep 300–700 km.
    _d = cat["_depth"]
    depth_classes = {
        "shallow": int((_d < 70).sum()),
        "intermediate": int(((_d >= 70) & (_d < 300)).sum()),
        "deep": int((_d >= 300).sum()),
        "unknown": int(_d.isna().sum()),
    }
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
        n_within_300_main=int(len(within_300_main)),
        table_cols=table_display_cols,
        table_original=table_original,
        map_all=map_all,
        map_mainshocks=map_mainshocks,
        map_300km=map_300km,
        depth_classes=depth_classes,
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
                sx, sy = _build_step_curve(manual_ct, years.min(), years.max(), mags.max())
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
    dm = float(request.form.get("dm", 0.1))
    Mc = float(request.form.get("mc", 4.45))
    M_LIMIT = float(request.form.get("m_limit", 5.0))
    M_MAX = float(request.form.get("m_max", 8.0))

    df, src_label, err = get_catalog_input(request)
    if err:
        return jsonify(error=err), 400

    cat = df.copy()
    cat["_mag"] = pd.to_numeric(cat[mag_col], errors="coerce")
    try:
        cat["_time"] = pd.to_datetime(cat[time_col])
        cat["_year"] = cat["_time"].dt.year + cat["_time"].dt.dayofyear / 365.25
    except Exception:
        cat["_year"] = pd.to_numeric(cat[time_col], errors="coerce")

    cat = cat.dropna(subset=["_mag", "_year"])
    T = cat["_year"].max() - cat["_year"].min()
    if T <= 0:
        return jsonify(error="Catalog duration is zero"), 400

    mags = cat["_mag"].values

    mmin = np.floor(mags.min() / dm) * dm
    edges = np.arange(mmin, M_MAX + dm, dm)
    inc_counts, _ = np.histogram(mags, bins=edges)
    m_centers = edges[:-1] + dm / 2.0
    cum_counts = inc_counts[::-1].cumsum()[::-1]

    inc_rates = inc_counts / T
    cum_rates = cum_counts / T

    m_fit = mags[mags >= Mc]
    if len(m_fit) < 5:
        return jsonify(error="Not enough events above Mc"), 400

    mean_mag = np.mean(m_fit)
    b_value = np.log10(np.e) / (mean_mag - (Mc - dm / 2))

    idx_ref = np.where(m_centers >= Mc)[0][0]
    Nref = cum_rates[idx_ref]
    a_value = np.log10(Nref) + b_value * m_centers[idx_ref] if Nref > 0 else 0

    m_grid = np.linspace(M_LIMIT, M_MAX, 600)
    model_cum = 10 ** (a_value - b_value * m_grid)

    cum_at_centers = 10 ** (a_value - b_value * m_centers)
    cum_at_next = 10 ** (a_value - b_value * (m_centers + dm))
    model_inc = np.maximum(cum_at_centers - cum_at_next, 1e-20)

    mask = (m_centers >= M_LIMIT) & (m_centers <= M_MAX)

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.semilogy(m_centers[mask], inc_rates[mask], "o", markersize=6,
                label="Observed Incremental Rate")
    ax.semilogy(m_centers[mask], model_inc[mask], "-", linewidth=1.5,
                label="Model Incremental Rate")
    ax.semilogy(m_centers[mask], cum_rates[mask], "s", markersize=6,
                label="Observed Cumulative Rate")
    ax.semilogy(m_grid, model_cum, "-", linewidth=2,
                label="Model Cumulative Rate")

    ax.set_xlabel("Magnitude", fontsize=12)
    ax.set_ylabel("Annual Occurrence Rate", fontsize=12)
    ax.set_title("Gutenberg–Richter Recurrence Plot", fontsize=13)
    ax.legend(fontsize=9)
    ax.grid(True, which="both", linestyle="--", linewidth=0.5)
    ax.set_xlim(M_LIMIT, M_MAX)

    eq_text = (
        r"$\log_{10}N(M \geq m) = a - bM$" "\n"
        f"a = {a_value:.3f}\n"
        f"b = {b_value:.3f}\n"
        f"T = {int(T)} years"
    )
    ax.text(0.02, 0.02, eq_text, transform=ax.transAxes, fontsize=10,
            verticalalignment="bottom",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    rates_csv = pd.DataFrame({
        "Magnitude": m_centers[mask],
        "Cum_Rate": cum_rates[mask],
        "Inc_Rate": inc_rates[mask],
    }).to_csv(index=False)

    return jsonify(
        plot=fig_to_b64(fig),
        a_value=round(a_value, 4),
        b_value=round(b_value, 4),
        duration=round(T, 1),
        n_events=int(len(m_fit)),
        rates_csv=rates_csv,
        source=src_label,
        qaqc=f"Source: {src_label}. GR: a={a_value:.4f}, b={b_value:.4f}, Mc={Mc}, T={T:.1f}yr, N={len(m_fit)}",
    )


# ── MFD (Magnitude-Frequency Distribution) ────
@app.route("/api/mfd", methods=["POST"])
def api_mfd():
    mag_col = request.form.get("mag_col", "mag")
    time_col = request.form.get("time_col", "time")
    depth_col = request.form.get("depth_col", "depth")
    dm = float(request.form.get("dm", 0.1))
    min_mag = float(request.form.get("min_mag", 4.5))
    max_mag = float(request.form.get("max_mag", 8.0))

    compl_texts = {
        "shallow": request.form.get("compl_shallow", ""),
        "mid-depth": request.form.get("compl_mid", ""),
        "deep": request.form.get("compl_deep", ""),
    }
    compl_tables = {k: _parse_compl_text(v) for k, v in compl_texts.items()}

    df, src_label, err = get_catalog_input(request)
    if err:
        return jsonify(error=err), 400

    cat = df.copy()
    cat["_mag"] = pd.to_numeric(cat[mag_col], errors="coerce")
    cat["_depth"] = pd.to_numeric(cat[depth_col], errors="coerce")
    try:
        cat["_time"] = pd.to_datetime(cat[time_col], utc=True)
        cat["_year"] = cat["_time"].dt.year
    except Exception:
        cat["_year"] = pd.to_numeric(cat[time_col], errors="coerce")

    cat = cat.dropna(subset=["_mag", "_year", "_depth"])
    cat = cat[cat["_mag"] >= min_mag]

    year_min = int(cat["_year"].min())
    year_max = int(cat["_year"].max())
    T_total = max(year_max - year_min, 1)

    def classify_depth(d):
        if 0 <= d < 35:
            return "shallow"
        if 35 <= d < 70:
            return "mid-depth"
        if 70 <= d < 700:
            return "deep"
        return None

    cat["_depth_class"] = cat["_depth"].apply(classify_depth)
    cat = cat.dropna(subset=["_depth_class"])

    depth_labels = {
        "shallow": "Shallow (0–35 km)",
        "mid-depth": "Mid-depth (35–70 km)",
        "deep": "Deep (70–700 km)",
    }

    def effective_duration(mag_val, compl_pairs, yr_max):
        """Return the number of years the catalog is complete for this magnitude."""
        if not compl_pairs:
            return max(yr_max - year_min, 1)
        compl_year = year_min  # default: catalog start
        for yr, mg in sorted(compl_pairs, key=lambda x: x[1]):
            if mg <= mag_val + dm / 2:
                compl_year = yr
        return max(yr_max - compl_year, 1)

    edges = np.arange(min_mag, max_mag + dm, dm)
    m_centers = edges[:-1] + dm / 2.0

    depth_plots = []
    oq_arbitrary = []
    all_rates = {}

    for dkey in ["shallow", "mid-depth", "deep"]:
        label = depth_labels[dkey]
        subset = cat[cat["_depth_class"] == dkey]
        n = len(subset)
        if subset.empty:
            continue

        mags = subset["_mag"].values
        compl_pairs = compl_tables.get(dkey, [])

        inc_counts, _ = np.histogram(mags, bins=edges)

        inc_rates = np.zeros(len(m_centers))
        for i, mc in enumerate(m_centers):
            dur = effective_duration(mc, compl_pairs, year_max)
            inc_rates[i] = inc_counts[i] / dur

        cum_rates = inc_rates[::-1].cumsum()[::-1]

        all_rates[dkey] = {
            "inc_rates": inc_rates,
            "cum_rates": cum_rates,
            "count": n,
        }

        m_fit = mags[mags >= min_mag]
        if len(m_fit) >= 5:
            mean_m = np.mean(m_fit)
            b_val = np.log10(np.e) / (mean_m - (min_mag - dm / 2))
            idx_ref = 0
            Nref = cum_rates[idx_ref]
            a_val = np.log10(max(Nref, 1e-20)) + b_val * m_centers[idx_ref]
            m_grid = np.linspace(min_mag, max_mag, 300)
            model_cum = 10 ** (a_val - b_val * m_grid)
        else:
            a_val, b_val = 0, 0
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
                f"a = {a_val:.3f}\nb = {b_val:.3f}\nT_eff varies by bin"
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
    colors = {"shallow": "#1f77b4", "mid-depth": "#ff7f0e", "deep": "#2ca02c"}
    for dkey in ["shallow", "mid-depth", "deep"]:
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

    # ── Overall GR fit ──
    all_mags = cat["_mag"].values
    m_fit_all = all_mags[all_mags >= min_mag]
    if len(m_fit_all) >= 5:
        mean_all = np.mean(m_fit_all)
        b_all = np.log10(np.e) / (mean_all - (min_mag - dm / 2))
        inc_all, _ = np.histogram(all_mags, bins=edges)
        cum_all = inc_all[::-1].cumsum()[::-1]
        cum_rate_all = cum_all / T_total
        Nref_all = cum_rate_all[0]
        a_all = np.log10(max(Nref_all, 1e-20)) + b_all * m_centers[0]
    else:
        a_all, b_all = 0, 0

    truncgr_xml = (
        "<truncGutenbergRichterMFD\n"
        f'  aValue="{a_all:.4f}"\n'
        f'  bValue="{b_all:.4f}"\n'
        f'  minMag="{min_mag:.1f}"\n'
        f'  maxMag="{max_mag:.1f}"\n'
        f'  binWidth="{dm}"/>'
    )

    csv_rows = [["magnitude", "depth_class", "inc_rate", "cum_rate"]]
    for dkey in ["shallow", "mid-depth", "deep"]:
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

    return jsonify(
        plot=combined_plot,
        depth_plots=depth_plots,
        total_events=len(cat),
        a_value=round(a_all, 4),
        b_value=round(b_all, 4),
        duration=T_total,
        oq_arbitrary=oq_arbitrary,
        oq_truncated_gr=truncgr_xml,
        oq_xml=oq_xml,
        rates_csv=rates_csv,
        source=src_label,
        qaqc=f"Source: {src_label}. MFD: {len(cat)} events, dm={dm}, "
             f"a={a_all:.4f}, b={b_all:.4f}, T={T_total}yr",
    )


# ─────────────────────────────────────────────
# Max Magnitude
# ─────────────────────────────────────────────
@app.route("/api/max_magnitude", methods=["POST"])
def api_max_magnitude():
    try:
        mag_col = request.form.get("mag_col", "mag")
        time_col = request.form.get("time_col", "time")

        df, src_label, err = get_catalog_input(request)
        if err:
            return jsonify(error=err)

        mag = pd.to_numeric(df[mag_col], errors="coerce").dropna()

        cat_data = {"magnitude": mag.values, "year": np.ones(len(mag))}
        try:
            dt = pd.to_datetime(df[time_col], errors="coerce")
            cat_data["year"] = dt.dt.year.values[:len(mag)]
            cat_data["month"] = dt.dt.month.values[:len(mag)]
            cat_data["day"] = dt.dt.day.values[:len(mag)]
        except Exception:
            cat_data["year"] = pd.to_numeric(df[time_col], errors="coerce").values[:len(mag)]

        from psha_preprocess.catalogue.checker import plot_magnitude_time_scatter
        fig_scatter = plot_magnitude_time_scatter(df, time_col, mag_col)
        plot_scatter = fig_to_b64(fig_scatter)

        # Cumulative moment release (Hanks & Kanamori)
        years = cat_data.get("year", np.arange(len(mag)))
        moment = 10 ** (1.5 * mag.values + 9.05)
        cum_moment = np.cumsum(moment)

        fig_cm, ax_cm = plt.subplots(figsize=(10, 5))
        ax_cm.plot(years[:len(cum_moment)], cum_moment, "b-", linewidth=1.5)
        ax_cm.set_xlabel("Year")
        ax_cm.set_ylabel("Cumulative Seismic Moment (N.m)")
        ax_cm.set_title("Cumulative Moment Release")
        ax_cm.grid(True, linestyle="--", alpha=0.4)
        plt.tight_layout()
        plot_moment = fig_to_b64(fig_cm)

        m_max_obs = float(mag.max())

        results = {
            "observed_mmax": round(m_max_obs, 2),
            "mmax_plus_05": round(m_max_obs + 0.5, 2),
            "n_events": len(mag),
            "mag_range": f"{mag.min():.1f} - {mag.max():.1f}",
        }

        return jsonify(
            plot_scatter=plot_scatter,
            plot_moment=plot_moment,
            results=results,
            source=src_label,
            qaqc=f"Source: {src_label}. Mmax: observed={m_max_obs:.2f}, "
                 f"Mmax+0.5={m_max_obs+0.5:.2f}, {len(mag)} events",
        )
    except Exception as e:
        return jsonify(error=str(e))


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, host="127.0.0.1",
            port=int(os.environ.get("PORT", 5000)))
