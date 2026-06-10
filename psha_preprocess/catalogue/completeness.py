"""
Stepp (1971/1972) completeness analysis and plotting.

Standalone implementation extracted from OpenQuake HMTK, using only
numpy, scipy, and matplotlib.
"""
import itertools
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import fmin_l_bfgs_b


# ── Stepp helper functions ──────────────────────────────────────────

def _piecewise_linear_scalar(params, xval):
    """Piecewise linear function for a scalar variable."""
    n_seg = len(params) // 2
    if n_seg == 1:
        return params[1] + params[0] * xval
    turning = params[n_seg:-1]
    intercept = params[-1]
    slopes = params[:n_seg]
    yval = intercept + slopes[0] * xval
    for i in range(1, n_seg):
        if xval <= turning[i - 1]:
            break
        yval += (slopes[i] - slopes[i - 1]) * (xval - turning[i - 1])
    else:
        if xval > turning[-1]:
            yval += (slopes[-1] - slopes[-2]) * (xval - turning[-1])
    return yval


def _bilinear_residuals(input_params, xvals, yvals, slope1_fit):
    """Residual sum-of-squares for bilinear fit with fixed first slope."""
    params = np.hstack([slope1_fit, input_params])
    residuals = sum(
        (yvals[i] - _piecewise_linear_scalar(params, xvals[i])) ** 2
        for i in range(len(xvals))
    )
    return residuals


def _fit_bilinear(xdata, ydata):
    """Fit bilinear model to sigma-lambda data, return completeness time."""
    fixed_slope = -0.5
    x_0 = [-1.0, xdata[int(len(xdata) / 2)], xdata[0]]
    bnds = ((None, fixed_slope), (0.0, None), (None, None))
    result, _, info = fmin_l_bfgs_b(
        _bilinear_residuals, x_0,
        args=(xdata, ydata, fixed_slope),
        approx_grad=True, bounds=bnds, disp=0,
    )
    if info["warnflag"] != 0:
        return np.nan, np.nan, np.nan * np.ones(len(xdata))
    model_line = 10.0 ** (fixed_slope * xdata + result[2])
    completeness_time = 10.0 ** result[1]
    return completeness_time, result[0], model_line


# ── Main Stepp analysis ────────────────────────────────────────────

def stepp_analysis(years, magnitudes, mag_bin=1.0, time_bin=5.0,
                   increment_lock=True):
    """Run Stepp (1971) completeness analysis.

    Args:
        years: Array of event years (or decimal years).
        magnitudes: Array of event magnitudes.
        mag_bin: Magnitude bin width.
        time_bin: Time bin width in years.
        increment_lock: Ensure completeness year doesn't decrease.

    Returns dict with keys:
        completeness_table: [[year, mag], ...] numpy array
        magnitude_bin: bin edges
        sigma: Poisson variance array
        model_line: expected rate array
        time_values: duration values
        end_year: latest year
    """
    years = np.asarray(years, dtype=float)
    magnitudes = np.asarray(magnitudes, dtype=float)

    end_year = np.floor(np.max(years))
    start_year = np.floor(np.min(years))

    # Magnitude bins
    min_mag = np.floor(np.min(magnitudes))
    max_mag = np.ceil(np.max(magnitudes)) + mag_bin
    mag_bins = np.arange(min_mag, max_mag, mag_bin)
    is_valid = np.logical_and(mag_bins - np.max(magnitudes) < mag_bin,
                              np.min(magnitudes) - mag_bins < mag_bin)
    mag_bins = mag_bins[is_valid]
    n_mags = len(mag_bins) - 1

    if n_mags < 1:
        return None

    # Time bins (descending from end_year)
    t_bins = np.arange(end_year - time_bin, start_year - time_bin, -time_bin)
    n_times = len(t_bins)

    if n_times < 2:
        return None

    # Count magnitudes per time-magnitude window
    counter = np.zeros([n_times, n_mags], dtype=int)
    for i in range(n_times):
        idx = years > t_bins[i]
        counter[i, :] = np.histogram(magnitudes[idx], mag_bins)[0]

    # Compute sigma_lambda
    sigma = np.zeros([n_times, n_mags], dtype=float)
    n_years = end_year - t_bins
    for j in range(n_mags):
        valid = counter[:, j] > 0
        if np.any(valid):
            n = counter[valid, j].astype(float)
            sigma[valid, j] = np.sqrt(n / n_years[valid]) / np.sqrt(n_years[valid])

    # Fit bilinear model to find completeness points
    comp_time = np.zeros(n_mags, dtype=float)
    model_line = np.zeros([n_times, n_mags], dtype=float)
    time_log = np.log10(n_years)

    for j in range(n_mags):
        valid = sigma[:, j] > 1e-9
        if np.sum(valid) < 3:
            comp_time[j] = np.nan
            model_line[:, j] = np.nan
        else:
            ct, _, ml = _fit_bilinear(time_log[valid], np.log10(sigma[valid, j]))
            comp_time[j] = ct
            model_line[valid, j] = ml

    # Apply increment lock
    if increment_lock:
        for j in range(1, len(comp_time)):
            if (comp_time[j] < comp_time[j - 1]) or np.isnan(comp_time[j]):
                comp_time[j] = comp_time[j - 1]

    completeness_table = np.column_stack([
        np.floor(end_year - comp_time), mag_bins[:-1]
    ])

    return {
        "completeness_table": completeness_table,
        "magnitude_bin": mag_bins,
        "sigma": sigma,
        "model_line": model_line,
        "time_values": n_years,
        "end_year": int(end_year),
    }


# ── Plotting ───────────────────────────────────────────────────────

MARKERS = ["s", "o", "^", "D", "p", "h", "8", "*", "d", "v", "<", ">", "H"]


def plot_stepp(result, title="", figsize=(10, 7)):
    """Create Stepp (1972) sigma-lambda vs time plot.

    Args:
        result: dict from stepp_analysis()
        title: optional title suffix

    Returns matplotlib Figure.
    """
    fig, ax = plt.subplots(figsize=figsize)

    mag_bins = result["magnitude_bin"]
    sigma = result["sigma"]
    model_line = result["model_line"]
    time_values = result["time_values"]
    comp_table = result["completeness_table"]
    end_year = result["end_year"]

    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    color_cycle = itertools.cycle(colors)
    marker_cycle = itertools.cycle(MARKERS)

    n_mags = len(mag_bins) - 1
    used_colors = []

    for i in range(n_mags):
        c = next(color_cycle)
        m = next(marker_cycle)
        used_colors.append(c)
        label = f"({mag_bins[i]:.0f}, {mag_bins[i+1]:.0f}]: {comp_table[i, 0]:.0f}"

        # Observed sigma
        valid = sigma[:, i] > 1e-9
        if np.any(valid):
            ax.loglog(time_values[valid], sigma[valid, i], linestyle="none",
                      marker=m, markersize=4, markerfacecolor=c,
                      markeredgecolor=c, label=label)

        # Model line
        if not np.all(np.isnan(model_line[:, i])):
            valid_ml = model_line[:, i] > 0
            if np.any(valid_ml):
                ax.loglog(time_values[valid_ml], model_line[valid_ml, i],
                          color=c, linewidth=0.7)

        # Breakpoint marker
        if not np.isnan(comp_table[i, 0]):
            xmarker = end_year - comp_table[i, 0]
            knee = model_line[:, i] > 0
            if np.any(knee) and xmarker > 0:
                try:
                    ymarker = 10.0 ** np.interp(
                        np.log10(xmarker),
                        np.log10(time_values[knee]),
                        np.log10(model_line[knee, i]))
                    ax.loglog(xmarker, ymarker, marker=m, markerfacecolor="white",
                              markeredgecolor=c, markersize=8)
                except Exception:
                    pass

    ax.legend(loc="lower left", frameon=False, fontsize="small")
    ax.set_xlabel("Time (years)")
    ax.set_ylabel(r"$\sigma_{\lambda} = \sqrt{\lambda} / \sqrt{T}$")
    ax.set_title("Stepp (1972) Completeness Analysis")
    ax.autoscale(enable=True, axis="both", tight=True)
    ax.grid(True, which="both", linestyle="--", alpha=0.3)
    plt.tight_layout()
    return fig


def _build_step_curve(completeness_table, t_min, t_max, m_max):
    """Build staircase step curve from completeness table.

    Table format: [[year, mag], ...] where each row means
    'complete for M >= mag from year onwards'.
    Returns (step_x, step_y) arrays for plotting.
    """
    ct = np.array(completeness_table)
    # Sort by magnitude descending (highest mag = oldest year = top-left)
    ct_desc = ct[ct[:, 1].argsort()[::-1]]

    step_x = [t_min]
    step_y = [ct_desc[0, 1]]  # start at highest magnitude

    for i, (yr, mg) in enumerate(ct_desc):
        # Horizontal line at current magnitude to this year
        step_x.append(yr)
        step_y.append(step_y[-1])
        # Vertical drop to next magnitude
        step_x.append(yr)
        step_y.append(mg)

    # Extend last segment to the right edge
    step_x.append(t_max + time_bin_default)
    step_y.append(step_y[-1])

    return step_x, step_y


# Default time bin for extending step curve
time_bin_default = 5


def plot_mag_time_density(years, magnitudes, mag_bin=0.5, time_bin=5,
                          completeness_table=None, title="", figsize=(10, 6)):
    """2D density plot with optional completeness step curve overlay.

    Uses 'viridis' colormap (OpenQuake style: dark purple → cyan → yellow).
    """
    global time_bin_default
    time_bin_default = time_bin

    years = np.asarray(years, dtype=float)
    magnitudes = np.asarray(magnitudes, dtype=float)

    t_min, t_max = years.min(), years.max()
    m_min, m_max = magnitudes.min(), magnitudes.max()

    t_edges = np.arange(t_min, t_max + time_bin, time_bin)
    m_edges = np.arange(m_min, m_max + mag_bin, mag_bin)

    H, xedges, yedges = np.histogram2d(years, magnitudes, bins=[t_edges, m_edges])
    H = H.T

    fig, ax = plt.subplots(figsize=figsize)
    H_masked = np.ma.masked_where(H == 0, H)
    from matplotlib.colors import LogNorm
    pcm = ax.pcolormesh(xedges, yedges, H_masked, cmap="viridis",
                        norm=LogNorm(vmin=1, vmax=max(H.max(), 2)))
    fig.colorbar(pcm, ax=ax, label="Event Count")

    ax.set_xlabel("Time (year)")
    ax.set_ylabel("Magnitude")
    ax.set_title("Magnitude-Time Density")
    ax.grid(True, linestyle="--", alpha=0.3, color="white")

    # Overlay completeness step curve
    if completeness_table is not None and len(completeness_table) > 0:
        sx, sy = _build_step_curve(completeness_table, t_min, t_max, m_max)
        ax.plot(sx, sy, color="#8b1a1a", linewidth=2.5, label="Completeness")
        ax.legend(fontsize=8)

    plt.tight_layout()
    return fig
