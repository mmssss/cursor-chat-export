"""Extract structured data from Cursor chat bubbles."""


def extract_selections(bubble: dict) -> list[dict]:
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


def extract_web_citations(bubble: dict) -> list[dict]:
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


def extract_bubble(bubble: dict, btype: int) -> dict | None:
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
        sels = extract_selections(bubble)
        if sels:
            msg["selections"] = sels
    else:
        cites = extract_web_citations(bubble)
        if cites:
            msg["web_citations"] = cites
    return msg
