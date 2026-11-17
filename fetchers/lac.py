"""
LAC fetcher — Library and Archives Canada (UFO sighting reports 1947-1981).

Library and Archives Canada holds approximately 9 500 digitised UFO sighting
reports collected by the Canadian government.  They are accessible through
the LAC open-access portal:
  https://recherche-collection-search.bac-lac.gc.ca/eng/home/record?app=fonandcol

The reports were digitised from the National Research Council of Canada files
(RG 77 series).  This fetcher:
  1. Queries the LAC search API for UFO/UAP records
  2. Downloads available PDF scans
  3. Feeds them through the LLM extraction pipeline

Usage:
    python -m fetchers.runner --sources lac
    python -m fetchers.runner --sources lac --since 2024-01-01
"""

from __future__ import annotations

import os
import json
import time
import datetime
import urllib.request
import urllib.parse
from pathlib import Path

LAC_SEARCH_API = "https://recherche-collection-search.bac-lac.gc.ca/eng/home/record"
LAC_API_BASE = "https://lac-bac.gc.ca"

# NRC UFO series finding aid reference
LAC_COLLECTION_QUERIES = [
    "UFO sighting National Research Council",
    "unidentified flying objects Canada RG 77",
    "flying saucers Canada government",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Prometheus-UAP-Fetcher/1.0; "
        "+https://github.com/imediacorp/Prometheus)"
    )
}

_RATE_DELAY_S = 2.0


def fetch(output_dir: str, since: str | None = None) -> list[str]:
    """
    Query LAC collection search and download available UAP PDF records.

    LAC does not expose a simple bulk-download API; this fetcher uses the
    collection search endpoint and follows available digitised-record links.

    Returns
    -------
    list[str]
        Paths to downloaded PDF files, or [] if the API is unreachable.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    since_dt: datetime.datetime | None = None
    if since:
        try:
            since_dt = datetime.datetime.fromisoformat(since)
        except ValueError:
            print(f"[lac] WARNING: could not parse --since '{since}'")

    seen_ids: set[str] = set()

    for query in LAC_COLLECTION_QUERIES:
        print(f"[lac] Searching LAC for: '{query}' ...")
        params = urllib.parse.urlencode({
            "q": query,
            "app": "fonandcol",
            "tab": "fonandcol",
            "num": 50,
        })
        url = f"{LAC_SEARCH_API}?{params}"
        req = urllib.request.Request(url, headers=_HEADERS)

        try:
            time.sleep(_RATE_DELAY_S)
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            print(f"[lac] WARNING: search failed — {exc}")
            continue

        # Extract PDF links from the results page (href pattern for LAC PDFs)
        import re
        pdf_links = re.findall(r'href=["\'](https?://[^"\']+\.pdf)["\']', html, re.IGNORECASE)

        for pdf_url in pdf_links:
            # Derive an ID from the URL
            rec_id = urllib.parse.quote(pdf_url.split("/")[-1].replace(".pdf", ""), safe="")
            if not rec_id or rec_id in seen_ids:
                continue
            seen_ids.add(rec_id)

            out_path = os.path.join(output_dir, f"lac_{rec_id[:60]}.pdf")
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
                saved.append(out_path)
                continue

            print(f"[lac] Downloading {rec_id} ...")
            time.sleep(_RATE_DELAY_S)
            req2 = urllib.request.Request(pdf_url, headers=_HEADERS)
            try:
                with urllib.request.urlopen(req2, timeout=120) as resp2:
                    data = resp2.read()
            except Exception as exc:
                print(f"[lac] WARNING: download failed for {rec_id}: {exc}")
                continue

            with open(out_path, "wb") as fh:
                fh.write(data)
            saved.append(out_path)
            print(f"[lac] Saved {rec_id} ({len(data) // 1024} KB)")

    print(f"[lac] Done. {len(saved)} files in {output_dir}")
    return saved


def ingest(files: list[str]) -> dict:
    """Run LLM extraction on LAC PDF files and ingest into Neo4j."""
    from etl import pdf_ocr, llm_extract

    records_loaded = 0
    records_skipped = 0

    for path in files:
        lac_id = Path(path).stem.replace("lac_", "")
        try:
            text = pdf_ocr.extract_text(path, max_pages=50)
        except Exception as exc:
            print(f"[lac] ERROR reading {path}: {exc}")
            records_skipped += 1
            continue

        chunk_size = 40_000
        chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

        for j, chunk in enumerate(chunks):
            chunk_id = f"{lac_id}-chunk{j + 1:03d}" if len(chunks) > 1 else lac_id
            try:
                llm_extract.extract_and_ingest(
                    source_name="LAC",
                    ext_id=chunk_id,
                    text=chunk,
                )
                records_loaded += 1
            except Exception as exc:
                print(f"[lac] ERROR extracting {chunk_id}: {exc}")
                records_skipped += 1

    return {"records_loaded": records_loaded, "records_skipped": records_skipped}
