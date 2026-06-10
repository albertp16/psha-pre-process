"""
Earthquake catalogue format detection and HMTK conversion.

Supports: USGS CSV, PHIVOLCS Excel, generic CSV with column mapping.
Output: tab-separated HMTK format compatible with CsvCatalogueParser.
"""
import io
import numpy as np
import pandas as pd


HMTK_COLUMNS = [
    "eventID", "Agency", "year", "month", "day", "hour", "minute", "second",
    "timeError", "longitude", "latitude", "SemiMajor90", "SemiMinor90",
    "ErrorStrike", "depth", "depthError", "magnitude", "sigmaMagnitude",
]


def detect_format(df, filename=""):
    """Auto-detect catalogue format from columns and filename."""
    cols_lower = {c.lower().strip() for c in df.columns}

    if {"time", "latitude", "longitude", "depth", "mag"} <= cols_lower:
        return "usgs"

    if {"eventid", "agency", "year", "month", "day", "magnitude"} <= cols_lower:
        return "hmtk"

    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in ("xlsx", "xls"):
        return "phivolcs"

    if {"year", "month", "day"} <= cols_lower:
        return "phivolcs"

    return "unknown"


def read_phivolcs_excel(raw_bytes):
    """Read PHIVOLCS earthquake catalogue from Excel bytes.

    Handles: header search, sub-header skip, multi-sheet concat,
    magnitude priority (Mw > Ms > Mb > Ml).
    """
    xls = pd.ExcelFile(io.BytesIO(raw_bytes), engine="openpyxl")
    frames = []

    for sheet in xls.sheet_names:
        raw = pd.read_excel(xls, sheet, header=None)

        # Find header row containing "Year" and "Month"
        header_row = None
        for i in range(min(20, len(raw))):
            row_vals = [str(v).strip() for v in raw.iloc[i] if pd.notna(v)]
            if "Year" in row_vals and "Month" in row_vals:
                header_row = i
                break

        if header_row is None:
            continue

        df = pd.read_excel(xls, sheet, header=header_row)
        df.columns = [str(c).strip() for c in df.columns]

        # Skip sub-header rows (contain unit descriptions, not data)
        mask = pd.to_numeric(df.iloc[:, 0], errors="coerce").notna()
        df = df[mask].reset_index(drop=True)

        frames.append(df)

    if not frames:
        raise ValueError("No valid data sheets found in Excel file")

    result = pd.concat(frames, ignore_index=True)

    # Build unified magnitude: Mw > Ms > Mb > Ml
    for col in result.columns:
        if col in ("Ml", "Mb", "Ms", "Mw"):
            result[col] = pd.to_numeric(result[col], errors="coerce")

    mag = pd.Series(np.nan, index=result.index)
    for pref in ["Ml", "Mb", "Ms", "Mw"]:  # last wins = highest priority
        if pref in result.columns:
            mag = mag.fillna(result[pref])
            mag = result[pref].combine_first(mag)
    result["_magnitude"] = mag

    return result


def convert_to_hmtk(df, source_format, column_map=None):
    """Convert a DataFrame to HMTK format.

    Args:
        df: Input DataFrame.
        source_format: One of "usgs", "phivolcs", "generic", "hmtk".
        column_map: For "generic" format - dict with keys:
            lat, lon, mag, time, depth (mapping to column names in df).

    Returns:
        DataFrame with HMTK columns.
    """
    out = pd.DataFrame(columns=HMTK_COLUMNS)

    if source_format == "hmtk":
        # Already HMTK - just ensure columns exist
        for col in HMTK_COLUMNS:
            if col in df.columns:
                out[col] = df[col].values
            else:
                out[col] = np.nan
        return out

    if source_format == "usgs":
        out = _convert_usgs(df)
    elif source_format == "phivolcs":
        out = _convert_phivolcs(df)
    elif source_format == "generic" and column_map:
        out = _convert_generic(df, column_map)
    else:
        raise ValueError(f"Unknown format: {source_format}")

    # Ensure all HMTK columns exist
    for col in HMTK_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan

    return out[HMTK_COLUMNS]


def _convert_usgs(df):
    """Convert USGS CSV to HMTK."""
    dt = pd.to_datetime(df["time"], errors="coerce", utc=True)

    out = pd.DataFrame()
    out["eventID"] = df.get("id", pd.Series(range(1, len(df) + 1)))
    out["Agency"] = "USGS"
    out["year"] = dt.dt.year
    out["month"] = dt.dt.month
    out["day"] = dt.dt.day
    out["hour"] = dt.dt.hour
    out["minute"] = dt.dt.minute
    out["second"] = dt.dt.second + dt.dt.microsecond / 1e6
    out["timeError"] = 0.0
    out["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    out["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    out["SemiMajor90"] = pd.to_numeric(df.get("horizontalError", np.nan), errors="coerce")
    out["SemiMinor90"] = pd.to_numeric(df.get("horizontalError", np.nan), errors="coerce")
    out["ErrorStrike"] = np.nan
    out["depth"] = pd.to_numeric(df["depth"], errors="coerce")
    out["depthError"] = pd.to_numeric(df.get("depthError", np.nan), errors="coerce")
    out["magnitude"] = pd.to_numeric(df["mag"], errors="coerce")
    out["sigmaMagnitude"] = pd.to_numeric(df.get("magError", np.nan), errors="coerce")

    return out


def _convert_phivolcs(df):
    """Convert PHIVOLCS Excel DataFrame to HMTK."""
    out = pd.DataFrame()
    n = len(df)
    out["eventID"] = [f"PHIVOLCS-{i + 1:06d}" for i in range(n)]
    out["Agency"] = "PHIVOLCS"

    # Map columns - handle variations in column names
    col_map = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl == "year":
            col_map["year"] = c
        elif cl == "month":
            col_map["month"] = c
        elif cl == "day":
            col_map["day"] = c
        elif cl == "hour":
            col_map["hour"] = c
        elif cl == "minute":
            col_map["minute"] = c
        elif cl == "second":
            col_map["second"] = c
        elif cl in ("north", "north latitude", "latitude"):
            col_map["lat"] = c
        elif cl in ("east", "east longitude", "longitude"):
            col_map["lon"] = c
        elif cl in ("depth", "depth (km)", "depth(km)"):
            col_map["depth"] = c

    for field in ["year", "month", "day", "hour", "minute", "second"]:
        if field in col_map:
            out[field] = pd.to_numeric(df[col_map[field]], errors="coerce")
        else:
            out[field] = 0

    out["timeError"] = 0.0
    out["longitude"] = pd.to_numeric(df.get(col_map.get("lon", "East"), np.nan), errors="coerce")
    out["latitude"] = pd.to_numeric(df.get(col_map.get("lat", "North"), np.nan), errors="coerce")
    out["depth"] = pd.to_numeric(df.get(col_map.get("depth", "Depth"), np.nan), errors="coerce")

    # Magnitude: use pre-computed _magnitude if available, else try columns
    if "_magnitude" in df.columns:
        out["magnitude"] = df["_magnitude"]
    else:
        mag = pd.Series(np.nan, index=df.index)
        for pref in ["Ml", "Mb", "Ms", "Mw"]:
            if pref in df.columns:
                vals = pd.to_numeric(df[pref], errors="coerce")
                mag = vals.combine_first(mag)
        out["magnitude"] = mag

    return out


def _convert_generic(df, column_map):
    """Convert generic CSV using user-provided column mapping."""
    out = pd.DataFrame()
    n = len(df)
    out["eventID"] = list(range(1, n + 1))
    out["Agency"] = "USER"

    time_col = column_map.get("time")
    if time_col and time_col in df.columns:
        dt = pd.to_datetime(df[time_col], errors="coerce")
        out["year"] = dt.dt.year
        out["month"] = dt.dt.month
        out["day"] = dt.dt.day
        out["hour"] = dt.dt.hour
        out["minute"] = dt.dt.minute
        out["second"] = dt.dt.second.astype(float)
    else:
        for f in ["year", "month", "day", "hour", "minute", "second"]:
            col = column_map.get(f)
            if col and col in df.columns:
                out[f] = pd.to_numeric(df[col], errors="coerce")

    out["timeError"] = 0.0

    for hmtk_field, map_key in [("latitude", "lat"), ("longitude", "lon"),
                                 ("depth", "depth"), ("magnitude", "mag")]:
        col = column_map.get(map_key)
        if col and col in df.columns:
            out[hmtk_field] = pd.to_numeric(df[col], errors="coerce")

    return out


def hmtk_to_csv_string(df):
    """Serialize HMTK DataFrame to tab-separated string."""
    return df.to_csv(sep="\t", index=False, na_rep="")
