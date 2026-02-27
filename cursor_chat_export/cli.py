"""Command-line interface — argument parsing and export orchestration."""

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .db import get_cursor_db_path, load_chat_data, extract_conversation
from .formatting import format_filename, format_markdown


def main():
    parser = argparse.ArgumentParser(
        description="Export Cursor IDE chat transcripts to markdown files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Reads chat data from Cursor's internal SQLite database and exports
conversations as markdown files with timestamped filenames.

Filename format: {YYYYMMDDTHHMM}_cursor_{slugified_chat_name}.md
Timestamp is the chat creation time in UTC.

Examples:
    cursor-chat-export -o /path/to/output/dir
    cursor-chat-export -o /path/to/output/dir --overwrite
    cursor-chat-export -o /path/to/output/dir --days 7
    cursor-chat-export -o /path/to/output/dir --filter "clickhouse backup"
    cursor-chat-export --list
    cursor-chat-export -o /path/to/output/dir --dry-run""",
    )
    parser.add_argument(
        "-o", "--output-dir", type=str, default=None,
        help="Directory to export markdown files to (required unless --list)",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Re-export all chats, overwriting already exported files",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Only export chats created in the last N days",
    )
    parser.add_argument(
        "--filter", type=str, default=None,
        help="Only export chats whose name contains this substring (case-insensitive)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List chats without exporting",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be exported without writing files",
    )
    parser.add_argument(
        "--min-messages", type=int, default=1,
        help="Minimum number of messages to include a chat (default: 1)",
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help="Path to Cursor state.vscdb (auto-detected if not set)",
    )

    args = parser.parse_args()

    # Validate: --output-dir is required unless --list
    if not args.list and not args.output_dir:
        parser.error("--output-dir / -o is required (unless using --list)")

    # Resolve database path
    db_path = Path(args.db) if args.db else get_cursor_db_path()
    if not db_path.exists():
        print(f"Error: Cursor database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    # Resolve output directory (may be None in --list mode)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None

    print(f"Database: {db_path}")
    if output_dir:
        print(f"Output:   {output_dir}")
    print()

    # Load chats
    chats = load_chat_data(db_path)
    print(f"Found {len(chats)} total chats in database")

    # Apply filters
    if args.days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        chats = [c for c in chats if c["created_at"] >= cutoff_ms]
        print(f"  After --days {args.days} filter: {len(chats)} chats")

    if args.filter:
        pattern = args.filter.lower()
        chats = [c for c in chats if pattern in (c["name"] or "").lower()]
        print(f"  After --filter '{args.filter}': {len(chats)} chats")

    # List mode
    if args.list:
        name_width = 60
        print()
        for chat in chats:
            dt = datetime.fromtimestamp(chat["created_at"] / 1000, tz=timezone.utc)
            fname = format_filename(chat["name"], chat["created_at"])
            # Collapse whitespace and truncate for display
            display_name = " ".join((chat["name"] or "").split()) or "(untitled)"
            if len(display_name) > name_width:
                display_name = display_name[:name_width - 1] + "\u2026"
            print(f"  {dt.strftime('%Y-%m-%d %H:%M')}  {display_name:{name_width}s}  -> {fname}")
        return

    # Create output directory
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Check existing exports (skip already exported unless --overwrite)
    existing_files = set()
    if not args.overwrite and output_dir.exists():
        existing_files = {f.name for f in output_dir.iterdir() if f.suffix == ".md"}

    # Track filenames used in this run to handle duplicates
    used_filenames: dict[str, int] = {}

    # Export
    exported = 0
    skipped_empty = 0
    skipped_exists = 0

    for chat in chats:
        fname = format_filename(chat["name"], chat["created_at"])

        # Deduplicate within the same run (different chats producing same filename)
        if fname in used_filenames:
            used_filenames[fname] += 1
            base, ext = fname.rsplit(".", 1)
            fname = f"{base}_{used_filenames[fname]}.{ext}"
        used_filenames[fname] = used_filenames.get(fname, 1)

        # Skip if already exported in a previous run
        if fname in existing_files:
            skipped_exists += 1
            continue

        messages = extract_conversation(db_path, chat)

        if len(messages) < args.min_messages:
            skipped_empty += 1
            continue

        if args.dry_run:
            print(f"  [DRY RUN] {fname}  ({len(messages)} messages)")
            exported += 1
            continue

        md = format_markdown(chat, messages)
        out_path = output_dir / fname
        out_path.write_text(md, encoding="utf-8")
        exported += 1
        print(f"  Exported: {fname}  ({len(messages)} messages)")

    print()
    print(f"Exported: {exported}")
    if skipped_exists:
        print(f"Skipped (already exists): {skipped_exists}")
    if skipped_empty:
        print(f"Skipped (< {args.min_messages} messages): {skipped_empty}")
