#!/usr/bin/env python3
"""Export Cursor IDE chat transcripts to markdown files."""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


# Cursor database location per platform
def get_cursor_db_path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Cursor"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "")) / "Cursor"
    else:  # Linux
        base = Path.home() / ".config" / "Cursor"
    return base / "User" / "globalStorage" / "state.vscdb"


def slugify(text: str, max_len: int = 50) -> str:
    """Convert text to a filesystem-safe slug."""
    if not text:
        return "untitled"
    # Lowercase and replace non-alphanumeric with underscores
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower())
    # Remove leading/trailing underscores
    slug = slug.strip("_")
    # Truncate to max_len, but don't cut in the middle of a word
    if len(slug) > max_len:
        slug = slug[:max_len]
        # Try to cut at an underscore boundary
        last_sep = slug.rfind("_")
        if last_sep > max_len // 2:
            slug = slug[:last_sep]
    return slug or "untitled"


def format_filename(name: str, created_at_ms: int) -> str:
    """Format the output filename from chat name and creation timestamp."""
    dt = datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc)
    ts = dt.strftime("%Y%m%dT%H%M")
    slug = slugify(name)
    return f"{ts}_cursor_{slug}.md"


def load_chat_data(db_path: Path) -> list[dict]:
    """Load all chat metadata from the Cursor database."""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        cur = db.cursor()

        cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
        chats = []
        for key, val in cur.fetchall():
            if val is None:
                continue
            try:
                data = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                continue

            composer_id = data.get("composerId", key.split(":", 1)[1] if ":" in key else key)
            name = data.get("name", "")
            created_at = data.get("createdAt", 0)

            if not created_at:
                continue

            chats.append({
                "composer_id": composer_id,
                "name": name,
                "created_at": created_at,
                "data": data,
            })

    chats.sort(key=lambda c: c["created_at"])
    return chats


def _extract_selections(bubble: dict) -> list[dict]:
    """Extract code selections from a bubble's context."""
    ctx = bubble.get("context", {})
    if not isinstance(ctx, dict):
        return []
    selections = []
    for sel in ctx.get("selections", []):
        raw_text = sel.get("rawText", "")
        if not raw_text or not raw_text.strip():
            continue
        uri = sel.get("uri", {})
        path = uri.get("path", "") if isinstance(uri, dict) else ""
        rng = sel.get("range", {})
        start_line = rng.get("selectionStartLineNumber")
        end_line = rng.get("positionLineNumber")
        selections.append({
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "text": raw_text.strip(),
        })
    return selections


def _extract_web_citations(bubble: dict) -> list[dict]:
    """Extract web citations not already present in the response text."""
    cites = bubble.get("webCitations", [])
    if not cites:
        return []
    text = bubble.get("text", "")
    seen_urls = set()
    result = []
    for c in cites:
        if isinstance(c, dict):
            url = c.get("url", "")
            title = c.get("title", "")
        elif isinstance(c, str):
            url, title = c, ""
        else:
            continue
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        # Skip citations already inlined in the response text
        if url in text:
            continue
        result.append({"url": url, "title": title})
    return result


def _extract_bubble(bubble: dict, btype: int) -> dict | None:
    """Build a message dict from a bubble, including attachments."""
    text = bubble.get("text", "")
    if not text or not text.strip():
        return None
    role = "user" if btype == 1 else "assistant"
    model = (bubble.get("modelInfo") or {}).get("modelName", "")
    msg = {
        "role": role,
        "model": model,
        "text": text.strip(),
    }
    if role == "user":
        sels = _extract_selections(bubble)
        if sels:
            msg["selections"] = sels
    else:
        cites = _extract_web_citations(bubble)
        if cites:
            msg["web_citations"] = cites
    return msg


def extract_conversation(db_path: Path, chat: dict) -> list[dict]:
    """Extract conversation messages from a chat.

    Handles both old format (inline conversation array) and
    new format (v11+, separate bubbleId keys).
    """
    data = chat["data"]
    messages = []

    # Old format: conversation array embedded in composerData
    conversation = data.get("conversation")
    if conversation and isinstance(conversation, list) and len(conversation) > 0:
        for bubble in conversation:
            btype = bubble.get("type")
            msg = _extract_bubble(bubble, btype)
            if msg:
                messages.append(msg)
        return messages

    # New format (v11+): headers + separate bubble keys
    headers = data.get("fullConversationHeadersOnly", [])
    if not headers:
        return messages

    composer_id = chat["composer_id"]
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        cur = db.cursor()

        for header in headers:
            bubble_id = header.get("bubbleId")
            btype = header.get("type")
            if not bubble_id:
                continue

            bubble_key = f"bubbleId:{composer_id}:{bubble_id}"
            cur.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (bubble_key,))
            row = cur.fetchone()
            if not row or row[0] is None:
                continue

            try:
                bubble = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                continue

            msg = _extract_bubble(bubble, btype)
            if msg:
                messages.append(msg)

    return messages


_EXT_TO_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".jsx": "jsx", ".rs": "rust", ".go": "go", ".java": "java", ".c": "c",
    ".cpp": "cpp", ".h": "cpp", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby",
    ".jl": "julia", ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".sql": "sql", ".html": "html", ".css": "css", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".xml": "xml",
    ".md": "markdown", ".r": "r", ".swift": "swift", ".kt": "kotlin",
    ".lua": "lua", ".zig": "zig", ".nim": "nim", ".ex": "elixir",
    ".exs": "elixir", ".erl": "erlang", ".hs": "haskell", ".ml": "ocaml",
    ".php": "php", ".pl": "perl", ".scala": "scala", ".dart": "dart",
}


def _lang_from_path(path: str) -> str:
    """Guess a markdown fence language tag from a file path."""
    if not path:
        return ""
    ext = os.path.splitext(path)[1].lower()
    return _EXT_TO_LANG.get(ext, "")


def _format_selections(selections: list[dict]) -> list[str]:
    """Format code selections as markdown blocks."""
    lines = []
    for sel in selections:
        path = sel.get("path", "")
        start = sel.get("start_line")
        end = sel.get("end_line")
        # Build the header line
        parts = []
        if path:
            parts.append(f"`{path}`")
        if start and end:
            parts.append(f"lines {start}\u2013{end}")
        elif start:
            parts.append(f"line {start}")
        header = " ".join(parts)
        if header:
            lines.append(f"_Selected code — {header}:_")
        else:
            lines.append("_Selected code:_")
        lines.append("")
        lang = _lang_from_path(path)
        lines.append(f"```{lang}")
        lines.append(sel["text"])
        lines.append("```")
        lines.append("")
    return lines


def _format_web_citations(citations: list[dict]) -> list[str]:
    """Format web citations as a markdown list."""
    lines = ["_Web sources:_", ""]
    for c in citations:
        title = c.get("title", "")
        url = c.get("url", "")
        if title:
            lines.append(f"- [{title}]({url})")
        else:
            lines.append(f"- {url}")
    lines.append("")
    return lines


def format_markdown(chat: dict, messages: list[dict]) -> str:
    """Format a chat as markdown, matching Cursor's built-in export format."""
    name = chat["name"] or "Untitled Chat"
    created_at = chat["created_at"]
    dt = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)

    lines = [
        f"# {name}",
        f"_Created on {dt.month}/{dt.day}/{dt.year} at {dt.strftime('%H:%M')} UTC | exported via export_cursor_chats.py_",
        "",
        "---",
        "",
    ]

    for msg in messages:
        if msg["role"] == "user":
            role_label = "**User**"
        else:
            model = msg.get("model", "")
            role_label = f"**AI** ({model})" if model else "**AI**"
        lines.append(role_label)
        lines.append("")

        # Code selections (user messages only)
        if msg.get("selections"):
            lines.extend(_format_selections(msg["selections"]))

        lines.append(msg["text"])
        lines.append("")

        # Web citations (assistant messages only)
        if msg.get("web_citations"):
            lines.extend(_format_web_citations(msg["web_citations"]))

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


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
    python export_cursor_chats.py -o /path/to/output/dir
    python export_cursor_chats.py -o /path/to/output/dir --overwrite
    python export_cursor_chats.py -o /path/to/output/dir --days 7
    python export_cursor_chats.py -o /path/to/output/dir --filter "clickhouse backup"
    python export_cursor_chats.py --list
    python export_cursor_chats.py -o /path/to/output/dir --dry-run""",
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
                display_name = display_name[:name_width - 1] + "…"
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


if __name__ == "__main__":
    main()
