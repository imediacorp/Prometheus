"""
FBI Vault fetcher — FBI Records: The Vault (UFO/UAP declassified memos).

Downloads known declassified FBI documents from the Vault and feeds them
through the LLM extraction pipeline.

The FBI Vault hosts scanned PDFs of historical UAP-related memos, primarily
from the 1940s–1970s.  Known series:
  - Hottel memo (1950)
  - Guy Hottel series
  - UFO series Part 1–17 (the main collection)

Since these are static documents, the fetcher maintains a manifest of known
URLs.  On re-runs it skips already-downloaded files.

Usage:
    python -m fetchers.runner --sources fbi_vault
"""

from __future__ import annotations

import os
import time
import urllib.request
from pathlib import Path

FBI_VAULT_BASE = "https://vault.fbi.gov"

# Known FBI Vault UAP/UFO document URLs (PDF series parts)
# Full list: https://vault.fbi.gov/UFO
FBI_VAULT_MANIFEST: list[dict] = [
    {"id": "hottel-memo-1950", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%201%20of%2016/view"},
    {"id": "ufo-part-01", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%201%20of%2016/at_download/file"},
    {"id": "ufo-part-02", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%202%20of%2016/at_download/file"},
    {"id": "ufo-part-03", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%203%20of%2016/at_download/file"},
    {"id": "ufo-part-04", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%204%20of%2016/at_download/file"},
    {"id": "ufo-part-05", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%205%20of%2016/at_download/file"},
    {"id": "ufo-part-06", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%206%20of%2016/at_download/file"},
    {"id": "ufo-part-07", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%207%20of%2016/at_download/file"},
    {"id": "ufo-part-08", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%208%20of%2016/at_download/file"},
    {"id": "ufo-part-09", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%209%20of%2016/at_download/file"},
    {"id": "ufo-part-10", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%2010%20of%2016/at_download/file"},
    {"id": "ufo-part-11", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%2011%20of%2016/at_download/file"},
    {"id": "ufo-part-12", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%2012%20of%2016/at_download/file"},
    {"id": "ufo-part-13", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%2013%20of%2016/at_download/file"},
    {"id": "ufo-part-14", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%2014%20of%2016/at_download/file"},
    {"id": "ufo-part-15", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%2015%20of%2016/at_download/file"},
    {"id": "ufo-part-16", "url": f"{FBI_VAULT_BASE}/ufo/UFO%20Part%2016%20of%2016/at_download/file"},
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Prometheus-UAP-Fetcher/1.0; "
        "+https://github.com/imediacorp/Prometheus)"
    )
}

_RATE_DELAY_S = 3.0


def fetch(output_dir: str, since: str | None = None) -> list[str]:
    """
    Download FBI Vault PDF documents to output_dir.

    Already-downloaded files are skipped (idempotent).
    `since` is ignored — these are static historical documents.

    Returns
    -------
    list[str]
        Paths to downloaded PDF files.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    for i, entry in enumerate(FBI_VAULT_MANIFEST, 1):
        doc_id = entry["id"]
        url = entry["url"]
        out_path = os.path.join(output_dir, f"fbi_{doc_id}.pdf")

        if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
            print(f"[fbi_vault] [{i}/{len(FBI_VAULT_MANIFEST)}] Already have {doc_id}, skipping")
            saved.append(out_path)
            continue

        print(f"[fbi_vault] [{i}/{len(FBI_VAULT_MANIFEST)}] Downloading {doc_id} ...")
        time.sleep(_RATE_DELAY_S)

        req = urllib.request.Request(url, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
        except Exception as exc:
            print(f"[fbi_vault] WARNING: could not download {url} — {exc}")
            continue

        if len(data) < 1024:
            print(f"[fbi_vault] WARNING: response for {doc_id} looks empty ({len(data)} bytes), skipping")
            continue

        with open(out_path, "wb") as fh:
            fh.write(data)

        saved.append(out_path)
        print(f"[fbi_vault] Saved {doc_id} ({len(data) // 1024} KB) → {out_path}")

    print(f"[fbi_vault] Done. {len(saved)} PDFs in {output_dir}")
    return saved


def ingest(files: list[str]) -> dict:
    """
    Extract text from each PDF and run LLM extraction into Neo4j.
    Large multi-page PDFs are processed page-by-page to stay within
    the 50 000-char Claude input cap.
    """
    from etl import pdf_ocr, llm_extract

    records_loaded = 0
    records_skipped = 0

    for path in files:
        doc_id = Path(path).stem.replace("fbi_", "")
        print(f"[fbi_vault] Extracting text from {Path(path).name} ...")

        try:
            text = pdf_ocr.extract_text(path, max_pages=50)
        except RuntimeError as exc:
            print(f"[fbi_vault] WARNING: {exc} — skipping {path}")
            records_skipped += 1
            continue
        except Exception as exc:
            print(f"[fbi_vault] ERROR reading {path}: {exc}")
            records_skipped += 1
            continue

        # Large FBI files can span hundreds of pages; chunk at 40 000 chars
        # to stay well within the 50K Claude cap
        chunk_size = 40_000
        chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

        for j, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}-chunk{j + 1:03d}" if len(chunks) > 1 else doc_id
            try:
                llm_extract.extract_and_ingest(
                    source_name="FBI_VAULT",
                    ext_id=chunk_id,
                    text=chunk,
                )
                records_loaded += 1
            except Exception as exc:
                print(f"[fbi_vault] ERROR extracting {chunk_id}: {exc}")
                records_skipped += 1

    return {"records_loaded": records_loaded, "records_skipped": records_skipped}
