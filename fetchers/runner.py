"""
Prometheus fetcher runner.

Calls each enabled source fetcher in sequence, then optionally runs ingestion.
Tracks the last successful fetch timestamp in .fetch_state.json so incremental
runs only process new records.

Usage:
    python -m fetchers.runner --sources nuforc,geipan
    python -m fetchers.runner --sources all
    python -m fetchers.runner --sources nuforc --no-ingest
    python -m fetchers.runner --sources all --output-dir /data/raw --since 2024-01-01

Environment variables (override Neo4j defaults in etl/ modules):
    NEO4J_URI       bolt://localhost:7687
    NEO4J_USER      neo4j
    NEO4J_PASSWORD  (required)
    OPENAI_API_KEY  (required for --embed step)
    ANTHROPIC_API_KEY (required for LLM extraction sources: aaro, fbi_vault, nara, lac)
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

# Map source names to their fetcher modules
_SOURCE_MODULES = {
    "nuforc":    "fetchers.nuforc",
    "geipan":    "fetchers.geipan",
    "aaro":      "fetchers.aaro",
    "fbi_vault": "fetchers.fbi_vault",
    "nara":      "fetchers.nara",
    "lac":       "fetchers.lac",
}

ALL_SOURCES = list(_SOURCE_MODULES.keys())

# Sources that use LLM extraction (require ANTHROPIC_API_KEY)
LLM_SOURCES = {"aaro", "fbi_vault", "nara", "lac"}

# Default output dir for downloaded raw data (not committed to git)
DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
STATE_FILE = os.path.join(os.path.dirname(__file__), "..", ".fetch_state.json")


def _load_state() -> dict:
    path = Path(STATE_FILE)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    Path(STATE_FILE).write_text(json.dumps(state, indent=2))


def _import_fetcher(source: str):
    import importlib
    mod_name = _SOURCE_MODULES[source]
    return importlib.import_module(mod_name)


def run_source(
    source: str,
    output_dir: str,
    since: str | None,
    do_ingest: bool,
    state: dict,
) -> dict:
    """Fetch and optionally ingest a single source. Returns updated state entry."""
    mod = _import_fetcher(source)
    source_dir = os.path.join(output_dir, source)

    effective_since = since or state.get(source, {}).get("last_fetch")
    if effective_since:
        print(f"\n[runner] {source.upper()} — incremental run since {effective_since}")
    else:
        print(f"\n[runner] {source.upper()} — full run (no prior state)")

    files = mod.fetch(source_dir, since=effective_since)
    if not files:
        print(f"[runner] {source.upper()} — no files fetched")
        return state.get(source, {})

    result = {"last_fetch": datetime.datetime.utcnow().isoformat(), "files_fetched": len(files)}

    if do_ingest:
        ingest_result = mod.ingest(files)
        result.update(ingest_result)
        print(
            f"[runner] {source.upper()} — "
            f"{ingest_result.get('records_loaded', 0)} loaded, "
            f"{ingest_result.get('records_skipped', 0)} skipped"
        )
    else:
        print(f"[runner] {source.upper()} — skipping ingest (--no-ingest)")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Prometheus UAP data fetcher runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sources",
        default="nuforc,geipan",
        help=(
            "Comma-separated list of sources to fetch. "
            f"Options: {', '.join(ALL_SOURCES)}, all. "
            "Default: nuforc,geipan"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for downloaded raw data (default: data/raw/)",
    )
    parser.add_argument(
        "--since",
        default=None,
        help=(
            "ISO date (YYYY-MM-DD) — override state file and fetch only records newer than this. "
            "By default uses the last-fetch timestamp from .fetch_state.json."
        ),
    )
    parser.add_argument(
        "--no-ingest",
        action="store_true",
        help="Download only; skip the Neo4j ingest step",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Ignore last-fetch state and perform a full re-fetch for selected sources",
    )
    args = parser.parse_args()

    # Resolve source list
    raw_sources = [s.strip().lower() for s in args.sources.split(",")]
    if "all" in raw_sources:
        sources = ALL_SOURCES
    else:
        invalid = [s for s in raw_sources if s not in _SOURCE_MODULES]
        if invalid:
            print(f"ERROR: unknown source(s): {', '.join(invalid)}", file=sys.stderr)
            print(f"Valid sources: {', '.join(ALL_SOURCES)}", file=sys.stderr)
            sys.exit(1)
        sources = raw_sources

    # Check for LLM-source prerequisites
    for src in sources:
        if src in LLM_SOURCES and not args.no_ingest:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                print(
                    f"WARNING: ANTHROPIC_API_KEY not set — "
                    f"ingest for '{src}' will fail at LLM extraction step"
                )

    state = {} if args.reset_state else _load_state()
    output_dir = os.path.abspath(args.output_dir)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print(f"[runner] Sources: {', '.join(sources)}")
    print(f"[runner] Output dir: {output_dir}")
    print(f"[runner] Ingest: {'no' if args.no_ingest else 'yes'}")

    overall_loaded = 0
    overall_skipped = 0

    for source in sources:
        try:
            result = run_source(
                source=source,
                output_dir=output_dir,
                since=args.since,
                do_ingest=not args.no_ingest,
                state=state,
            )
            state[source] = result
            overall_loaded += result.get("records_loaded", 0)
            overall_skipped += result.get("records_skipped", 0)
        except Exception as exc:
            print(f"[runner] ERROR in {source}: {exc}")
            import traceback
            traceback.print_exc()

    _save_state(state)
    print(f"\n[runner] Complete. Total loaded: {overall_loaded}, skipped: {overall_skipped}")
    print(f"[runner] State saved to {Path(STATE_FILE).resolve()}")


if __name__ == "__main__":
    main()
