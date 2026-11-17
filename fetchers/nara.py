"""
NARA fetcher — National Archives and Records Administration (RG 615, UAP records).

Fetches declassified UAP/UFO records from NARA's online catalog.

NARA hosts Project Blue Book records (RG 341) and newer UAP Task Force releases
(RG 615) through its catalog API:
  https://catalog.archives.gov/api/v2/

This fetcher queries NARA's catalog for UAP-related archival records,
downloads available PDFs, and feeds them through the LLM extraction pipeline.

Usage:
    python -m fetchers.runner --sources nara
    python -m fetchers.runner --sources nara --since 2024-01-01
"""

from __future__ import annotations

import os
import json
import time
import datetime
import urllib.request
import urllib.parse
from pathlib import Path

NARA_API_BASE = "https://catalog.archives.gov/api/v2"

# Search terms known to return UAP/UFO records
NARA_SEARCH_TERMS = [
    "unidentified aerial phenomena",
    "UAP Task Force",
    "Project Blue Book",
    "unidentified flying objects UFO declassified",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Prometheus-UAP-Fetcher/1.0; "
        "+https://github.com/imediacorp/Prometheus)"
    )
}

_RATE_DELAY_S = 2.0
_PAGE_SIZE = 50


def _search_catalog(query: str, offset: int = 0) -> dict:
    params = urllib.parse.urlencode({
        "q": query,
        "resultTypes": "item",
        "rows": _PAGE_SIZE,
        "offset": offset,
        "type": "item",
    })
    url = f"{NARA_API_BASE}/records?{params}"
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[nara] WARNING: catalog search failed — {exc}")
        return {}


def fetch(output_dir: str, since: str | None = None) -> list[str]:
    """
    Query NARA catalog for UAP records and download available PDFs.

    Returns
    -------
    list[str]
        Paths to downloaded files.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    since_dt: datetime.datetime | None = None
    if since:
        try:
            since_dt = datetime.datetime.fromisoformat(since)
        except ValueError:
            print(f"[nara] WARNING: could not parse --since '{since}'")

    seen_ids: set[str] = set()

    for term in NARA_SEARCH_TERMS:
        print(f"[nara] Searching: '{term}' ...")
        offset = 0

        while True:
            time.sleep(_RATE_DELAY_S)
            result = _search_catalog(term, offset)
            hits = result.get("body", {}).get("hits", {})
            items = hits.get("hits", [])

            if not items:
                break

            for item in items:
                src = item.get("_source", {})
                nara_id = str(src.get("naId", ""))
                if not nara_id or nara_id in seen_ids:
                    continue
                seen_ids.add(nara_id)

                # Try to find a digital object (PDF) URL
                digital_objects = src.get("digitalObjects", [])
                for obj in digital_objects:
                    obj_url = obj.get("objectUrl", "")
                    if not obj_url.lower().endswith(".pdf"):
                        continue

                    out_path = os.path.join(output_dir, f"nara_{nara_id}.pdf")
                    if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
                        saved.append(out_path)
                        break

                    print(f"[nara] Downloading NARA ID {nara_id} ...")
                    time.sleep(_RATE_DELAY_S)
                    req = urllib.request.Request(obj_url, headers=_HEADERS)
                    try:
                        with urllib.request.urlopen(req, timeout=120) as resp:
                            data = resp.read()
                    except Exception as exc:
                        print(f"[nara] WARNING: download failed for {nara_id}: {exc}")
                        break

                    with open(out_path, "wb") as fh:
                        fh.write(data)
                    saved.append(out_path)
                    print(f"[nara] Saved NARA {nara_id} ({len(data) // 1024} KB)")
                    break

            total = hits.get("total", {})
            total_count = total.get("value", 0) if isinstance(total, dict) else int(total)
            offset += _PAGE_SIZE
            if offset >= total_count:
                break

    print(f"[nara] Done. {len(saved)} files in {output_dir}")
    return saved


def ingest(files: list[str]) -> dict:
    """Run LLM extraction on NARA PDF files and ingest into Neo4j."""
    from etl import pdf_ocr, llm_extract

    records_loaded = 0
    records_skipped = 0

    for path in files:
        nara_id = Path(path).stem.replace("nara_", "")
        try:
            text = pdf_ocr.extract_text(path, max_pages=50)
        except Exception as exc:
            print(f"[nara] ERROR reading {path}: {exc}")
            records_skipped += 1
            continue

        chunk_size = 40_000
        chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

        for j, chunk in enumerate(chunks):
            chunk_id = f"{nara_id}-chunk{j + 1:03d}" if len(chunks) > 1 else nara_id
            try:
                llm_extract.extract_and_ingest(
                    source_name="NARA",
                    ext_id=chunk_id,
                    text=chunk,
                )
                records_loaded += 1
            except Exception as exc:
                print(f"[nara] ERROR extracting {chunk_id}: {exc}")
                records_skipped += 1

    return {"records_loaded": records_loaded, "records_skipped": records_skipped}
