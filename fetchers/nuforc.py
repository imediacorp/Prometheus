"""
NUFORC fetcher — National UFO Reporting Center.

Downloads the cleaned NUFORC CSV dataset (hosted on GitHub/Kaggle) and
ingests it into Neo4j via the standard ETL pipeline.

The cleaned dataset (~200K records) is maintained at:
  https://raw.githubusercontent.com/planetsig/ufo-reports/master/csv-data/ufo-scrubbed-geocoded-time-standardized.csv

For incremental runs the fetcher filters by `datetime` >= `since`.

Usage:
    python -m fetchers.runner --sources nuforc
    python -m fetchers.runner --sources nuforc --since 2024-01-01
"""

from __future__ import annotations

import os
import io
import csv
import datetime
import urllib.request
from pathlib import Path

NUFORC_CSV_URL = (
    "https://raw.githubusercontent.com/planetsig/ufo-reports/master/"
    "csv-data/ufo-scrubbed-geocoded-time-standardized.csv"
)

# Column names in the planetsig cleaned dataset
_COLS = [
    "datetime", "city", "state", "country", "shape",
    "duration (seconds)", "duration (hours/min)", "comments",
    "date posted", "latitude", "longitude",
]


def fetch(output_dir: str, since: str | None = None) -> list[str]:
    """
    Download the NUFORC CSV to output_dir.

    Parameters
    ----------
    output_dir : str
        Directory where the CSV will be saved.
    since : str | None
        ISO date string (YYYY-MM-DD).  Only records with datetime >= since
        are written to the output file (reduces downstream load on incremental
        runs).  When None, the full dataset is downloaded.

    Returns
    -------
    list[str]
        List containing the path of the saved CSV file, or [] on error.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    out_path = os.path.join(output_dir, "nuforc.csv")

    since_dt: datetime.datetime | None = None
    if since:
        try:
            since_dt = datetime.datetime.fromisoformat(since)
        except ValueError:
            print(f"[nuforc] WARNING: could not parse --since date '{since}', fetching all records")

    print(f"[nuforc] Downloading dataset from {NUFORC_CSV_URL} ...")
    try:
        with urllib.request.urlopen(NUFORC_CSV_URL, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"[nuforc] ERROR: download failed — {exc}")
        return []

    lines = raw.splitlines()
    reader = csv.DictReader(io.StringIO(raw))

    if since_dt is None:
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            fh.write(raw)
        total = len(lines) - 1  # subtract header
        print(f"[nuforc] Saved full dataset ({total} records) → {out_path}")
        return [out_path]

    # Incremental filter
    kept: list[dict] = []
    fieldnames = reader.fieldnames or _COLS
    for row in reader:
        raw_dt = row.get("datetime", "").strip()
        try:
            rec_dt = datetime.datetime.strptime(raw_dt, "%m/%d/%Y %H:%M")
        except ValueError:
            kept.append(row)  # keep unparseable rows rather than drop
            continue
        if rec_dt >= since_dt:
            kept.append(row)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    print(f"[nuforc] Saved {len(kept)} records (since {since}) → {out_path}")
    return [out_path]


def ingest(files: list[str]) -> dict:
    """
    Normalize and load NUFORC CSV files into Neo4j.

    Returns
    -------
    dict
        {records_loaded, records_skipped}
    """
    from etl import normalize_nuforc, load_neo4j

    records_loaded = 0
    records_skipped = 0

    for path in files:
        print(f"[nuforc] Normalizing {path} ...")
        try:
            records = normalize_nuforc.load_csv(path)
        except Exception as exc:
            print(f"[nuforc] ERROR normalizing {path}: {exc}")
            records_skipped += 1
            continue

        print(f"[nuforc] Ingesting {len(records)} records into Neo4j ...")
        try:
            loaded = load_neo4j.load(records)
            records_loaded += loaded
        except Exception as exc:
            print(f"[nuforc] ERROR loading {path}: {exc}")
            records_skipped += len(records)

    return {"records_loaded": records_loaded, "records_skipped": records_skipped}
