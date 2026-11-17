"""
Normalizes NUFORC CSV exports into the standard record dict format.

Expected CSV columns (Kaggle/GitHub cleaned exports):
  id, datetime, city, state, country, shape, duration (seconds),
  duration (hours/min), comments, date posted, latitude, longitude
"""

import pandas as pd
from .deterministic_id import generate_id


def normalize(df: pd.DataFrame) -> list[dict]:
    records = []
    for idx, row in df.iterrows():
        ext_id = str(row.get("id", idx))
        dt = pd.to_datetime(row.get("datetime"), utc=True, errors="coerce")
        if pd.isnull(dt):
            continue

        lat = _float_or_none(row.get("latitude"))
        lon = _float_or_none(row.get("longitude"))

        # duration: prefer numeric seconds column, fall back to 0
        dur_raw = row.get("duration (seconds)") or row.get("duration_seconds") or 0
        try:
            duration = int(float(dur_raw))
        except (ValueError, TypeError):
            duration = 0

        records.append({
            "source_name": "NUFORC",
            "external_case_id": ext_id,
            "temp_incident_id": generate_id("NUFORC", ext_id),
            "datetime_utc": dt.isoformat(),
            "city": _clean_str(row.get("city")).title(),
            "region": _clean_str(row.get("state")).upper(),
            "country": _clean_str(row.get("country", "USA")).upper(),
            "lat": lat,
            "lon": lon,
            "shape": _clean_str(row.get("shape", "Unknown")).title(),
            "duration_seconds": duration,
            "raw_text": _clean_str(row.get("comments") or row.get("text", "")),
            "observer_type": "Civilian",
            "classification": "Unverified",
        })

    return records


def load_csv(path: str) -> list[dict]:
    df = pd.read_csv(path, low_memory=False)
    return normalize(df)


def _float_or_none(val) -> float | None:
    try:
        f = float(val)
        return f if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


def _clean_str(val) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return ""
    return str(val).strip()
