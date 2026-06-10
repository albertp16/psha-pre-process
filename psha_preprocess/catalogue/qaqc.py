"""
Catalogue quality control: duplicate detection, magnitude checks, gap analysis.
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _haversine_km(lat1, lon1, lat2, lon2):
    """Haversine distance in km between two points."""
    R = 6371.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = (np.sin(dlat / 2) ** 2 +
         np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) *
         np.sin(dlon / 2) ** 2)
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def find_duplicates(df, lat_col, lon_col, time_col, mag_col,
                    time_tol_sec=60, dist_tol_km=50, mag_tol=0.5):
    """Find potentially duplicate events using time-sorted sliding window.

    Returns DataFrame with columns: idx1, idx2, time_diff_sec, dist_km, mag_diff.
    """
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    mag = pd.to_numeric(df[mag_col], errors="coerce")
    dt = pd.to_datetime(df[time_col], errors="coerce")

    valid = lat.notna() & lon.notna() & mag.notna() & dt.notna()
    idx = df.index[valid]
    lat_v = lat[valid].values
    lon_v = lon[valid].values
    mag_v = mag[valid].values
    dt_v = dt[valid].values

    # Sort by time
    order = np.argsort(dt_v)
    lat_v, lon_v, mag_v, dt_v, idx = (
        lat_v[order], lon_v[order], mag_v[order], dt_v[order], idx[order])

    duplicates = []
    n = len(dt_v)
    tol_ns = np.timedelta64(int(time_tol_sec), "s")

    for i in range(n - 1):
        j = i + 1
        while j < n and (dt_v[j] - dt_v[i]) <= tol_ns:
            tdiff = (dt_v[j] - dt_v[i]) / np.timedelta64(1, "s")
            mdiff = abs(mag_v[j] - mag_v[i])
            if mdiff <= mag_tol:
                dist = _haversine_km(lat_v[i], lon_v[i], lat_v[j], lon_v[j])
                if dist <= dist_tol_km:
                    duplicates.append({
                        "idx1": int(idx[i]),
                        "idx2": int(idx[j]),
                        "time_diff_sec": round(tdiff, 1),
                        "dist_km": round(dist, 1),
                        "mag_diff": round(mdiff, 2),
                    })
            j += 1

    return pd.DataFrame(duplicates)


def check_magnitude_consistency(df, mag_col):
    """Check magnitude column for anomalies."""
    mag = pd.to_numeric(df[mag_col], errors="coerce")

    counts, edges = np.histogram(mag.dropna(), bins=np.arange(-1, 12, 0.5))

    return {
        "n_total": len(mag),
        "n_nan": int(mag.isna().sum()),
        "n_negative": int((mag < 0).sum()),
        "n_suspicious": int((mag > 10).sum()),
        "mean": round(float(mag.mean()), 2) if mag.notna().any() else None,
        "median": round(float(mag.median()), 2) if mag.notna().any() else None,
        "std": round(float(mag.std()), 2) if mag.notna().any() else None,
        "min": round(float(mag.min()), 2) if mag.notna().any() else None,
        "max": round(float(mag.max()), 2) if mag.notna().any() else None,
        "hist_edges": edges.tolist(),
        "hist_counts": counts.tolist(),
    }


def find_gaps(df, time_col, n_top=10):
    """Find largest temporal gaps and events-per-year counts."""
    dt = pd.to_datetime(df[time_col], errors="coerce").dropna().sort_values()

    if len(dt) < 2:
        return {"gaps": [], "events_per_year": {}}

    deltas = dt.diff().iloc[1:]
    delta_days = deltas.dt.total_seconds() / 86400.0

    top_idx = delta_days.nlargest(n_top).index
    gaps = []
    for i in top_idx:
        loc = dt.index.get_loc(i)
        gaps.append({
            "start": str(dt.iloc[loc - 1].date()) if loc > 0 else "",
            "end": str(dt.iloc[loc].date()),
            "days": round(float(delta_days[i]), 1),
        })

    # Events per year
    years = dt.dt.year.value_counts().sort_index()
    events_per_year = {str(k): int(v) for k, v in years.items()}

    return {"gaps": gaps, "events_per_year": events_per_year}


def plot_qaqc_summary(df, lat_col, lon_col, time_col, mag_col, depth_col,
                      mag_stats=None, gap_info=None):
    """Generate QAQC summary plots.

    Returns list of (Figure, title) tuples.
    """
    plots = []

    # 1. Magnitude histogram
    mag = pd.to_numeric(df[mag_col], errors="coerce").dropna()
    fig1, ax1 = plt.subplots(figsize=(8, 5))
    if len(mag) > 0:
        bins = np.arange(mag.min() - 0.25, mag.max() + 0.5, 0.25)
        ax1.hist(mag, bins=bins, color="#3b82f6", edgecolor="k", linewidth=0.3)
        if mag.min() < 0:
            ax1.axvline(0, color="red", linestyle="--", label="M=0")
        if mag.max() > 9:
            ax1.axvline(10, color="red", linestyle="--", label="M=10 (suspicious)")
            ax1.legend()
    ax1.set_xlabel("Magnitude")
    ax1.set_ylabel("Count")
    ax1.set_title("Magnitude Distribution")
    ax1.grid(True, axis="y", linestyle="--", alpha=0.4)
    plt.tight_layout()
    plots.append((fig1, "Magnitude Distribution"))

    # 2. Events per year
    dt = pd.to_datetime(df[time_col], errors="coerce").dropna()
    if len(dt) > 0:
        years = dt.dt.year
        year_counts = years.value_counts().sort_index()
        fig2, ax2 = plt.subplots(figsize=(10, 5))
        ax2.bar(year_counts.index, year_counts.values, color="#22c55e",
                edgecolor="k", linewidth=0.3)
        ax2.set_xlabel("Year")
        ax2.set_ylabel("Number of Events")
        ax2.set_title("Events per Year")
        ax2.grid(True, axis="y", linestyle="--", alpha=0.4)
        plt.tight_layout()
        plots.append((fig2, "Events per Year"))

    # 3. Depth vs Magnitude
    depth = pd.to_numeric(df[depth_col], errors="coerce") if depth_col else None
    if depth is not None and depth.notna().any():
        fig3, ax3 = plt.subplots(figsize=(8, 6))
        mask = mag.index.isin(depth.dropna().index)
        ax3.scatter(mag[mask], depth.reindex(mag[mask].index), s=5, alpha=0.4,
                    color="#f59e0b")
        ax3.invert_yaxis()
        ax3.set_xlabel("Magnitude")
        ax3.set_ylabel("Depth (km)")
        ax3.set_title("Depth vs Magnitude")
        ax3.grid(True, linestyle="--", alpha=0.4)
        plt.tight_layout()
        plots.append((fig3, "Depth vs Magnitude"))

    return plots
