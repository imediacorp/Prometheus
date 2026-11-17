"""
AARO fetcher — All-domain Anomaly Resolution Office (US DoD).

Scrapes the public AARO case listing at https://aaro.mil/Report-a-UAP/UAP-Report-Summary/
and converts each case page to a standard ETL record for LLM extraction.

AARO does not publish a bulk CSV export; each case is a separate HTML page.
The fetcher:
  1. Downloads the master case listing HTML
  2. Extracts individual case URLs
  3. For each case, downloads the page and extracts visible text
  4. Saves the text as .txt files for downstream LLM extraction

Usage:
    python -m fetchers.runner --sources aaro
"""

from __future__ import annotations

import os
import re
import time
import datetime
import urllib.request
import urllib.parse
from pathlib import Path
from html.parser import HTMLParser

AARO_BASE = "https://www.aaro.mil"
AARO_LISTING = "https://www.aaro.mil/Report-a-UAP/UAP-Report-Summary/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Prometheus-UAP-Fetcher/1.0; "
        "+https://github.com/imediacorp/Prometheus)"
    )
}

_RATE_DELAY_S = 2.0  # be polite to aaro.mil


class _TextExtractor(HTMLParser):
    """Strips HTML tags and returns visible text."""

    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []
        self._skip_tags = {"script", "style", "noscript", "head"}
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag.lower() in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._chunks.append(stripped)

    def get_text(self) -> str:
        return "\n".join(self._chunks)


def _fetch_url(url: str) -> str | None:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"[aaro] WARNING: failed to fetch {url} — {exc}")
        return None


def _extract_case_urls(html: str) -> list[str]:
    """Find relative case-detail links in the listing page."""
    # Links typically look like /Report-a-UAP/UAP-Report-Summary/Case-XXXX/
    pattern = re.compile(
        r'href=["\'](/Report-a-UAP/UAP-Report-Summary/[^"\'#?]+/)["\']',
        re.IGNORECASE,
    )
    found = pattern.findall(html)
    # De-duplicate, filter out the base listing URL itself
    seen: set[str] = set()
    urls: list[str] = []
    for path in found:
        full = AARO_BASE + path
        if full not in seen and "UAP-Report-Summary/" in path and path.count("/") >= 4:
            seen.add(full)
            urls.append(full)
    return urls


def fetch(output_dir: str, since: str | None = None) -> list[str]:
    """
    Download AARO case text files to output_dir.

    Each case becomes a .txt file named by its URL slug.
    Returns a list of saved .txt file paths.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    since_dt: datetime.datetime | None = None
    if since:
        try:
            since_dt = datetime.datetime.fromisoformat(since)
        except ValueError:
            print(f"[aaro] WARNING: could not parse --since '{since}'")

    print(f"[aaro] Fetching case listing from {AARO_LISTING} ...")
    listing_html = _fetch_url(AARO_LISTING)
    if not listing_html:
        print("[aaro] ERROR: could not load AARO case listing")
        return []

    case_urls = _extract_case_urls(listing_html)
    print(f"[aaro] Found {len(case_urls)} case URLs")

    saved: list[str] = []
    for i, url in enumerate(case_urls, 1):
        # Derive a filesystem-safe ID from the URL slug
        slug = url.rstrip("/").split("/")[-1]
        out_path = os.path.join(output_dir, f"aaro_{slug}.txt")

        # Skip already-fetched cases on incremental runs
        if os.path.exists(out_path):
            if since_dt is None:
                saved.append(out_path)
                continue
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(out_path))
            if mtime >= since_dt:
                saved.append(out_path)
                continue

        time.sleep(_RATE_DELAY_S)

        html = _fetch_url(url)
        if not html:
            continue

        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()

        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(f"SOURCE_URL: {url}\n\n")
            fh.write(text)

        saved.append(out_path)
        print(f"[aaro] [{i}/{len(case_urls)}] Saved {slug}")

    print(f"[aaro] Done. {len(saved)} case files in {output_dir}")
    return saved


def ingest(files: list[str]) -> dict:
    """
    Run LLM extraction on each AARO case text file and ingest into Neo4j.
    """
    from etl import llm_extract

    records_loaded = 0
    records_skipped = 0

    for path in files:
        slug = Path(path).stem  # e.g. aaro_Case-2024-001
        ext_id = slug.replace("aaro_", "")

        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except Exception as exc:
            print(f"[aaro] ERROR reading {path}: {exc}")
            records_skipped += 1
            continue

        try:
            llm_extract.extract_and_ingest(
                source_name="AARO_PORTAL",
                ext_id=ext_id,
                text=text,
            )
            records_loaded += 1
        except Exception as exc:
            print(f"[aaro] ERROR extracting {path}: {exc}")
            records_skipped += 1

    return {"records_loaded": records_loaded, "records_skipped": records_skipped}
