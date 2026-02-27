# cursor-chat-export

Export [Cursor IDE](https://cursor.com) chat transcripts to markdown files.

Reads chat data directly from Cursor's internal SQLite database and writes each conversation as a standalone `.md` file with a timestamped filename.

## Requirements

- Python 3.10+
- No external dependencies (uses only `sqlite3`, `json`, `re`, `argparse` from stdlib)

## Filename format

```
{timestamp}_cursor_{slug}.md
```

- **Timestamp** — chat creation time in UTC, formatted as `%Y%m%dT%H%M`
- **Prefix** — literal `cursor_`
- **Slug** — lowercased, underscore-separated chat name, truncated to 50 characters at a word boundary

Examples:

```
20260227T0729_cursor_clickhouse_backup_system.md
20260224T1011_cursor_scraper_deribit_thorough_review.md
20260225T1427_cursor_kafka_and_clickhouse_logging_behavior.md
```

## Usage

```bash
# Export all chats (incremental — skips already exported files)
python export_cursor_chats.py -o /path/to/output/dir

# Export all chats including already exported ones
python export_cursor_chats.py -o /path/to/output/dir --overwrite

# Export only chats from the last 7 days
python export_cursor_chats.py -o /path/to/output/dir --days 7

# Export chats matching a name pattern
python export_cursor_chats.py -o /path/to/output/dir --filter "clickhouse backup"

# List chats without exporting
python export_cursor_chats.py --list

# Preview what would be exported
python export_cursor_chats.py -o /path/to/output/dir --dry-run

# Override minimum message count (default: 2)
python export_cursor_chats.py -o /path/to/output/dir --min-messages 4

# Use a custom database path
python export_cursor_chats.py -o /path/to/output/dir --db /path/to/state.vscdb
```

## Options

| Flag | Description |
|------|-------------|
| `-o`, `--output-dir` | Directory to write `.md` files to (created automatically; required unless `--list`) |
| `--overwrite` | Re-export everything, even if the file already exists |
| `--days N` | Only include chats created in the last N days |
| `--filter TEXT` | Only include chats whose name contains TEXT (case-insensitive) |
| `--list` | Print chat list with filenames, don't write anything |
| `--dry-run` | Show what would be exported without writing files |
| `--min-messages N` | Skip chats with fewer than N messages (default: 1) |
| `--db PATH` | Path to Cursor's `state.vscdb` (auto-detected if omitted) |

## How it works

### Database location

Cursor stores all persistent state in a SQLite database:

| Platform | Path |
|----------|------|
| Linux | `~/.config/Cursor/User/globalStorage/state.vscdb` |
| macOS | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` |
| Windows | `%APPDATA%/Cursor/User/globalStorage/state.vscdb` |

The database is opened in **read-only mode** (`?mode=ro`), so there is zero risk of corrupting Cursor's state.

### Data model

Chat data lives in the `cursorDiskKV` table. Two formats exist depending on when the chat was created:

**Old format** (pre-v11) — The full conversation is stored inline in a single `composerData:<uuid>` row:

```json
{
  "composerId": "008e96ba-...",
  "name": "Testing Maximum Open Files",
  "createdAt": 1732097537069,
  "conversation": [
    {"type": 1, "text": "How do I..."},
    {"type": 2, "text": "You can use..."}
  ]
}
```

**New format** (v11+) — The `composerData` row only contains headers; actual message content is in separate `bubbleId:` rows:

```
composerData:<composerId>  →  { "fullConversationHeadersOnly": [{"bubbleId": "...", "type": 1}, ...] }
bubbleId:<composerId>:<bubbleId>  →  { "type": 1, "text": "How do I...", ... }
```

The script handles both formats transparently.

### Message types

- `type: 1` — User message
- `type: 2` — AI/assistant message (model name extracted from `modelInfo.modelName` when available)

Only messages with non-empty `text` are exported. Tool calls, thinking blocks, and structural bubbles (which have empty text) are skipped — the export contains just the readable conversation.

### Incremental export

By default, the script scans the output directory for existing `.md` files and skips any chat whose filename matches. This makes it safe to run repeatedly — only new chats are exported.

### Filename deduplication

When multiple chats produce the same filename (e.g., several untitled chats created in the same minute), a counter suffix is appended: `_2`, `_3`, etc.

## Output format

Each exported file looks like this (matching Cursor's built-in export format):

```markdown
# ClickHouse backup system
_Created on 2/27/2026 at 07:29 UTC | exported via export_cursor_chats.py_

---

**User**

How to make backup of ClickHouse database?

---

**AI** (claude-4.6-opus-high-thinking)

Great question. Here's the full picture: ...

---
```

## License

MIT
