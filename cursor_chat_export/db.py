"""Cursor database access — locate, load, and query chat data."""

import json
import os
import sqlite3
import sys
from pathlib import Path

from .extract import extract_bubble


def get_cursor_db_path() -> Path:
    """Return the default Cursor state database path for the current platform."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Cursor"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "")) / "Cursor"
    else:  # Linux
        base = Path.home() / ".config" / "Cursor"
    return base / "User" / "globalStorage" / "state.vscdb"


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
            msg = extract_bubble(bubble, btype)
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

            msg = extract_bubble(bubble, btype)
            if msg:
                messages.append(msg)

    return messages
