"""
Entry point for the Prometheus ETL pipeline.

Subcommands:
    load           — normalize a CSV and write to Neo4j
    resolve        — run entity resolution on loaded incidents
    stats          — show current graph counts
    extract        — run LLM extraction on a PDF or text file and ingest into Neo4j
    embed          — generate and store embeddings for all pending SourceRecords
    vector-resolve — run vector-enhanced entity resolution

Usage:
    python -m etl.ingest load --source nuforc --file /path/to/nuforc.csv
    python -m etl.ingest load --source geipan --file /path/to/geipan.csv --dry-run
    python -m etl.ingest resolve
    python -m etl.ingest stats
    python -m etl.ingest extract --source FBI_VAULT --id memo-1947-04 --file /path/to/doc.pdf
    python -m etl.ingest embed
    python -m etl.ingest vector-resolve
"""

import argparse
import sys
from . import normalize_nuforc, normalize_geipan, load_neo4j, entity_resolution

SOURCES = {
    "nuforc": normalize_nuforc.load_csv,
    "geipan": normalize_geipan.load_csv,
}


def cmd_load(args):
    print(f"[load] Source: {args.source.upper()}")
    print(f"[load] File:   {args.file}")

    loader = SOURCES[args.source]
    try:
        records = loader(args.file)
    except FileNotFoundError:
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR during normalization: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[load] Normalized {len(records)} records")

    if args.dry_run:
        print("[load] Dry run — skipping Neo4j write")
        if records:
            print("[load] Sample record:")
            for k, v in records[0].items():
                print(f"  {k}: {v!r}")
        return

    print(f"[load] Writing to Neo4j in batches of {args.batch_size}...")
    total = load_neo4j.load(records, batch_size=args.batch_size)
    print(f"[load] Done. {total} records written.")


def cmd_resolve(args):
    print("[resolve] Running entity resolution pipeline...")
    result = entity_resolution.run()
    print(f"[resolve] Complete.")
    print(f"  Total incidents:    {result.get('total_incidents', 'n/a')}")
    print(f"  Auto-merged:        {result.get('auto_merged', 'n/a')}")
    print(f"  Flagged for review: {result.get('flagged_for_review', 'n/a')}")
    print(f"  Sources repointed:  {result.get('repointed', 'n/a')}")


def cmd_stats(args):
    result = entity_resolution.stats()
    if not result:
        print("[stats] No data returned — graph may be empty.")
        return
    print("[stats] Graph summary:")
    print(f"  Total incidents:    {result.get('total_incidents', 0)}")
    print(f"  Auto-merged:        {result.get('auto_merged', 0)}")
    print(f"  Flagged for review: {result.get('flagged_for_review', 0)}")


def cmd_extract(args):
    from . import pdf_ocr, llm_extract

    path: str = args.file
    if path.lower().endswith(".pdf"):
        print(f"[extract] Reading PDF: {path}")
        try:
            text = pdf_ocr.extract_text(path)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"[extract] Reading text file: {path}")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except FileNotFoundError:
            print(f"ERROR: File not found: {path}", file=sys.stderr)
            sys.exit(1)

    print(f"[extract] Text length: {len(text)} chars")

    if args.dry_run:
        print("[extract] Dry run — skipping Claude + Neo4j")
        print(f"[extract] Preview (first 500 chars):\n{text[:500]}")
        return

    result = llm_extract.extract_and_ingest(
        source_name=args.source,
        ext_id=args.id,
        text=text,
    )
    print(f"[extract] Done. Summary: {result.summary}")
    print(f"[extract] Phenomena: {[p.shape for p in result.phenomena]}")
    print(f"[extract] Observers: {result.observer_types}")


def cmd_embed(args):
    from . import embeddings
    print("[embed] Checking embedding stats...")
    stats = embeddings.embedding_stats()
    print(f"  Total SourceRecords: {stats.get('total', 0)}")
    print(f"  Already embedded:    {stats.get('embedded', 0)}")
    print(f"  Pending:             {stats.get('pending', 0)}")

    if stats.get("pending", 0) == 0:
        print("[embed] Nothing to embed.")
        return

    print(f"[embed] Embedding {stats['pending']} records (batch size {args.batch_size})...")
    result = embeddings.embed_pending(batch_size=args.batch_size)
    print(f"[embed] Done. {result['total_embedded']} records embedded in {result['total_batches']} batches.")


def cmd_vector_resolve(args):
    from queries import vector_resolution
    result = vector_resolution.run()
    vector_resolution.print_report(result)


def main():
    parser = argparse.ArgumentParser(description="Prometheus UAP Neo4j pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    # load subcommand
    p_load = sub.add_parser("load", help="Normalize a CSV and ingest into Neo4j")
    p_load.add_argument("--source", required=True, choices=SOURCES.keys())
    p_load.add_argument("--file", required=True, help="Path to the CSV file")
    p_load.add_argument("--batch-size", type=int, default=1000)
    p_load.add_argument("--dry-run", action="store_true", help="Normalize only, skip Neo4j write")

    # resolve subcommand
    sub.add_parser("resolve", help="Run entity resolution on loaded incidents")

    # stats subcommand
    sub.add_parser("stats", help="Show current graph resolution counts")

    # embed subcommand
    p_embed = sub.add_parser("embed", help="Generate and store embeddings for pending SourceRecords")
    p_embed.add_argument("--batch-size", type=int, default=100, help="Records per OpenAI API call (default 100)")

    # vector-resolve subcommand
    sub.add_parser("vector-resolve", help="Run vector-enhanced entity resolution")

    # extract subcommand
    p_extract = sub.add_parser("extract", help="LLM-extract entities from a PDF or text file")
    p_extract.add_argument("--source", required=True, help="Source name (e.g. FBI_VAULT, NARA, LAC)")
    p_extract.add_argument("--id", required=True, help="Unique external case/document ID")
    p_extract.add_argument("--file", required=True, help="Path to PDF or plain-text file")
    p_extract.add_argument("--dry-run", action="store_true", help="Extract text only, skip Claude + Neo4j")

    args = parser.parse_args()

    if args.command == "load":
        cmd_load(args)
    elif args.command == "resolve":
        cmd_resolve(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "extract":
        cmd_extract(args)
    elif args.command == "embed":
        cmd_embed(args)
    elif args.command == "vector-resolve":
        cmd_vector_resolve(args)


if __name__ == "__main__":
    main()
