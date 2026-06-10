"""
Catalogue analysis plots: map, depth histogram, time-magnitude scatter/density.

All functions accept a pandas DataFrame with user-mapped column names
and return matplotlib Figure objects.
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm


def _parse_decimal_year(df, time_col):
    """Convert a time column to decimal years."""
    dt = pd.to_datetime(df[time_col], errors="coerce")
    year = dt.dt.year
    day_of_year = dt.dt.dayofyear
    days_in_year = np.where(dt.dt.is_leap_year, 366.0, 365.0)
    return year + day_of_year / days_in_year


def plot_catalogue_map(df, lat_col, lon_col, mag_col, depth_col=None):
    """Scatter plot of events colored by magnitude."""
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    mag = pd.to_numeric(df[mag_col], errors="coerce")

    mask = lat.notna() & lon.notna() & mag.notna()
    lat, lon, mag = lat[mask], lon[mask], mag[mask]

    fig, ax = plt.subplots(figsize=(10, 8))
    sizes = mag ** 2 * 3
    sc = ax.scatter(lon, lat, s=sizes, c=mag, cmap="YlOrRd",
                    alpha=0.7, edgecolors="k", linewidths=0.3)
    fig.colorbar(sc, ax=ax, label="Magnitude", shrink=0.7)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(f"Earthquake Catalogue ({mask.sum()} events)")
    ax.set_aspect("equal")
    ax.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()
    return fig


def plot_depth_histogram(df, depth_col, bin_width=10.0):
    """Histogram of event depths."""
    depths = pd.to_numeric(df[depth_col], errors="coerce").dropna()
    depths = depths[depths >= 0]

    if len(depths) == 0:
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.text(0.5, 0.5, "No valid depth data", ha="center", va="center",
                transform=ax.transAxes, fontsize=14)
        return fig

    max_depth = depths.max()
    bins = np.arange(0, max_depth + bin_width, bin_width)
    counts, edges = np.histogram(depths, bins=bins)

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(edges[:-1], counts, height=bin_width * 0.9, align="edge",
            color="#3b82f6", edgecolor="k", linewidth=0.3)
    ax.invert_yaxis()
    ax.set_xlabel("Number of Events")
    ax.set_ylabel("Depth (km)")
    ax.set_title(f"Depth Distribution ({len(depths)} events)")
    ax.grid(True, axis="x", linestyle="--", alpha=0.4)
    plt.tight_layout()
    return fig


def plot_magnitude_time_scatter(df, time_col, mag_col):
    """Scatter plot of magnitude vs decimal year."""
    mag = pd.to_numeric(df[mag_col], errors="coerce")
    dec_year = _parse_decimal_year(df, time_col)

    mask = mag.notna() & dec_year.notna()
    mag, dec_year = mag[mask], dec_year[mask]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(dec_year, mag, "o", markersize=3, alpha=0.5, color="#3b82f6")
    ax.set_xlabel("Year")
    ax.set_ylabel("Magnitude")
    ax.set_title(f"Magnitude-Time Distribution ({mask.sum()} events)")
    ax.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()
    return fig


def plot_magnitude_time_density(df, time_col, mag_col, mag_bin=0.5, time_bin=10):
    """2D density plot (pcolormesh) of magnitude vs time."""
    mag = pd.to_numeric(df[mag_col], errors="coerce")
    dec_year = _parse_decimal_year(df, time_col)

    mask = mag.notna() & dec_year.notna()
    mag, dec_year = mag[mask].values, dec_year[mask].values

    if len(mag) == 0:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "No valid data", ha="center", va="center",
                transform=ax.transAxes, fontsize=14)
        return fig

    t_min, t_max = dec_year.min(), dec_year.max()
    m_min, m_max = mag.min(), mag.max()

    t_edges = np.arange(t_min, t_max + time_bin, time_bin)
    m_edges = np.arange(m_min, m_max + mag_bin, mag_bin)

    H, xedges, yedges = np.histogram2d(dec_year, mag, bins=[t_edges, m_edges])
    H = H.T  # rows = magnitude, cols = time

    fig, ax = plt.subplots(figsize=(10, 6))

    # Mask zeros for log scale
    H_masked = np.ma.masked_where(H == 0, H)
    pcm = ax.pcolormesh(xedges, yedges, H_masked, cmap="hot_r",
                        norm=LogNorm(vmin=1, vmax=max(H.max(), 2)))
    fig.colorbar(pcm, ax=ax, label="Number of Events")
    ax.set_xlabel("Year")
    ax.set_ylabel("Magnitude")
    ax.set_title(f"Magnitude-Time Density (mag_bin={mag_bin}, time_bin={time_bin})")
    ax.grid(True, linestyle="--", alpha=0.3)
    plt.tight_layout()
    return fig
