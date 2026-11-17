"""
Normalizes GEIPAN CSV exports into the standard record dict format.

Expected CSV columns (CNES GEIPAN public export):
  id_cas, date_obs, commune, departement, lat, lon,
  forme, duree_sec, resume, classification
"""

import pandas as pd
from .deterministic_id import generate_id


# GEIPAN official classification descriptions
GEIPAN_CLASS = {
    "A": "Explained",
    "B": "Probably_Explained",
    "C": "Insufficient_Data",
    "D": "Unexplained",
}


def normalize(df: pd.DataFrame) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        ext_id = str(row["id_cas"])
        dt = pd.to_datetime(row.get("date_obs"), utc=True, errors="coerce")
        if pd.isnull(dt):
            continue

        lat = _float_or_none(row.get("lat"))
        lon = _float_or_none(row.get("lon"))

        raw_class = _clean_str(row.get("classification", "D")).upper()
        classification = GEIPAN_CLASS.get(raw_class, raw_class)

        try:
            duration = int(float(row.get("duree_sec") or 0))
        except (ValueError, TypeError):
            duration = 0

        records.append({
            "source_name": "GEIPAN",
            "external_case_id": ext_id,
            "temp_incident_id": generate_id("GEIPAN", ext_id),
            "datetime_utc": dt.isoformat(),
            "city": _clean_str(row.get("commune")).title(),
            "region": _clean_str(row.get("departement")),
            "country": "FRANCE",
            "lat": lat,
            "lon": lon,
            "shape": _clean_str(row.get("forme", "Unknown")).title(),
            "duration_seconds": duration,
            "raw_text": _clean_str(row.get("resume", "")),
            "observer_type": "Civilian_Gendarmerie",
            "classification": classification,
        })

    return records


def load_csv(path: str) -> list[dict]:
    df = pd.read_csv(path, low_memory=False)
    return normalize(df)


def _float_or_none(val) -> float | None:
    try:
        f = float(val)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clean_str(val) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return ""
    return str(val).strip()
