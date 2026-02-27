"""Markdown formatting — filenames, slugs, and full chat rendering."""

import os
import re
from datetime import datetime, timezone


def _escape_md(text: str) -> str:
    """Escape markdown-special characters in plain text."""
    return re.sub(r'([_*\[\]\\])', r'\\\1', text)


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
            lines.append(f"- [{_escape_md(title)}]({url})")
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
        f"# {_escape_md(name)}",
        f"_Created on {dt.month}/{dt.day}/{dt.year} at {dt.strftime('%H:%M')} UTC | exported via cursor-chat-export_",
        "",
        "---",
        "",
    ]

    for msg in messages:
        if msg["role"] == "user":
            role_label = "**User**"
        else:
            model = msg.get("model", "")
            role_label = f"**AI** ({_escape_md(model)})" if model else "**AI**"
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
