"""
GEIPAN fetcher — Groupe d'Études et d'Informations sur les Phénomènes Aérospatiaux Non-identifiés (CNES).

Downloads the GEIPAN open-data CSV export and ingests it into Neo4j.

GEIPAN publishes its case catalogue through the CNES open-data portal:
  https://donneesouvertes.cnes.fr/geipan/

The dataset URL below points to the standard CSV export (~3 000 cases).

Usage:
    python -m fetchers.runner --sources geipan
    python -m fetchers.runner --sources geipan --since 2024-01-01
"""

from __future__ import annotations

import os
import datetime
import csv
import io
import urllib.request
from pathlib import Path

# CNES open-data export — direct CSV link
GEIPAN_CSV_URL = (
    "https://donneesouvertes.cnes.fr/geipan/wp-content/uploads/"
    "cas_enquetes.csv"
)

# Fallback: community mirror maintained by GEIPAN researchers
GEIPAN_MIRROR_URL = (
    "https://raw.githubusercontent.com/dbelavy/geipan-data/main/"
    "cas_enquetes.csv"
)


def fetch(output_dir: str, since: str | None = None) -> list[str]:
    """
    Download the GEIPAN CSV to output_dir.

    Parameters
    ----------
    output_dir : str
        Directory where the CSV will be saved.
    since : str | None
        ISO date string.  Records with observation date < since are dropped.

    Returns
    -------
    list[str]
        Path of saved file, or [] on error.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    out_path = os.path.join(output_dir, "geipan.csv")

    since_dt: datetime.datetime | None = None
    if since:
        try:
            since_dt = datetime.datetime.fromisoformat(since)
        except ValueError:
            print(f"[geipan] WARNING: could not parse --since '{since}', fetching all records")

    raw: str | None = None
    for url in (GEIPAN_CSV_URL, GEIPAN_MIRROR_URL):
        print(f"[geipan] Trying {url} ...")
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            break
        except Exception as exc:
            print(f"[geipan] WARNING: {url} failed — {exc}")

    if raw is None:
        print("[geipan] ERROR: all download attempts failed")
        return []

    if since_dt is None:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(raw)
        lines = raw.strip().splitlines()
        print(f"[geipan] Saved full dataset ({len(lines) - 1} records) → {out_path}")
        return [out_path]

    # Incremental filter on date_observation column
    reader = csv.DictReader(io.StringIO(raw), delimiter=";")
    fieldnames = reader.fieldnames or []
    kept: list[dict] = []

    # GEIPAN date column may be named 'date_observation' or 'date_obs'
    date_col = next(
        (c for c in fieldnames if "date" in c.lower() and "obs" in c.lower()),
        fieldnames[0] if fieldnames else "date_observation",
    )

    for row in reader:
        raw_date = row.get(date_col, "").strip()
        try:
            rec_dt = datetime.datetime.strptime(raw_date[:10], "%Y-%m-%d")
        except ValueError:
            kept.append(row)
            continue
        if rec_dt >= since_dt:
            kept.append(row)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(kept)

    print(f"[geipan] Saved {len(kept)} records (since {since}) → {out_path}")
    return [out_path]


def ingest(files: list[str]) -> dict:
    """
    Normalize and load GEIPAN CSV files into Neo4j.

    Returns
    -------
    dict
        {records_loaded, records_skipped}
    """
    from etl import normalize_geipan, load_neo4j

    records_loaded = 0
    records_skipped = 0

    for path in files:
        print(f"[geipan] Normalizing {path} ...")
        try:
            records = normalize_geipan.load_csv(path)
        except Exception as exc:
            print(f"[geipan] ERROR normalizing {path}: {exc}")
            records_skipped += 1
            continue

        print(f"[geipan] Ingesting {len(records)} records into Neo4j ...")
        try:
            loaded = load_neo4j.load(records)
            records_loaded += loaded
        except Exception as exc:
            print(f"[geipan] ERROR loading {path}: {exc}")
            records_skipped += len(records)

    return {"records_loaded": records_loaded, "records_skipped": records_skipped}
