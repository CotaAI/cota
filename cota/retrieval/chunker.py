"""Markdown heading-aware chunker for knowledge files."""
import re
from typing import Dict, List, Optional

_FRONTMATTER = re.compile(r'\A---\n(.*?\n)---\n', re.DOTALL)
_HEADING = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
_FENCE = re.compile(r'^(`{3,}|~{3,})', re.MULTILINE)
_MAX_CHUNK_CHARS = 1200


def parse_frontmatter(text):
    """Extract optional YAML frontmatter and remaining body."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    import yaml
    try:
        meta = yaml.safe_load(match.group(1))
    except Exception:
        meta = {}
    return meta if isinstance(meta, dict) else {}, text[match.end():]


def chunk_markdown(text, source=""):
    """Split Markdown by headings, preserving heading chain context.

    Returns list of dicts: {id, heading_chain, title, text, source}.
    Headings inside fenced code blocks are ignored.
    """
    meta, body = parse_frontmatter(text)
    doc_title = meta.get('title', '')

    fenced_ranges = _fenced_ranges(body)
    splits = _split_by_headings(body, fenced_ranges)

    if not splits:
        text = body.strip()
        heading_chain = [doc_title] if doc_title else []
        title = doc_title or source
        parts = _split_oversized(text, _MAX_CHUNK_CHARS)
        base_id = f"{source}" if source else "chunk-0"
        if len(parts) == 1:
            return [{'id': base_id, 'heading_chain': heading_chain,
                     'title': title, 'text': text, 'source': source}]
        return [{'id': base_id if i == 0 else f"{base_id}~{i}",
                 'heading_chain': list(heading_chain), 'title': title,
                 'text': part, 'source': source}
                for i, part in enumerate(parts)]

    chunks = []
    heading_stack = []
    all_ids = set()
    seq = 0
    for level, title, content in splits:
        if level is not None:
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))

        chain = [doc_title] if doc_title and (not heading_stack or heading_stack[0][1] != doc_title) else []
        chain.extend(h[1] for h in heading_stack)

        chunk_text = content.strip()
        if not chunk_text:
            continue

        chunk_title = ' > '.join(chain) if chain else source
        base_id = f"{source}#{chunk_title}" if source else chunk_title

        for sub_text in _split_oversized(chunk_text, _MAX_CHUNK_CHARS):
            chunk_id = base_id
            while chunk_id in all_ids:
                seq += 1
                chunk_id = f"{base_id}~{seq}"
            all_ids.add(chunk_id)
            chunks.append({'id': chunk_id, 'heading_chain': list(chain),
                           'title': chunk_title, 'text': sub_text, 'source': source})
    return chunks or [{'id': source, 'heading_chain': [], 'title': source,
                       'text': body.strip(), 'source': source}]


def _fenced_ranges(text):
    """Return list of (start, end) byte ranges for fenced code blocks."""
    ranges = []
    start = None
    fence_marker = None
    for match in _FENCE.finditer(text):
        marker = match.group(1)
        if start is None:
            start = match.start()
            fence_marker = marker[0]
        elif marker[0] == fence_marker and len(marker) >= len(fence_marker):
            ranges.append((start, match.end()))
            start = None
            fence_marker = None
    return ranges


def _in_fence(pos, ranges):
    for start, end in ranges:
        if start <= pos < end:
            return True
        if pos < start:
            break
    return False


def _split_oversized(text, max_chars):
    """Split text exceeding max_chars at paragraph boundaries, then hard-wrap."""
    if len(text) <= max_chars:
        return [text]
    paragraphs = re.split(r'\n\n+', text)
    parts = []
    current = []
    current_len = 0
    for para in paragraphs:
        for segment in _hard_split(para, max_chars):
            added = len(segment) + (2 if current else 0)
            if current and current_len + added > max_chars:
                parts.append('\n\n'.join(current))
                current = [segment]
                current_len = len(segment)
            else:
                current.append(segment)
                current_len += added
    if current:
        parts.append('\n\n'.join(current))
    return parts or [text]


def _hard_split(text, max_chars):
    """Split a single paragraph that exceeds max_chars at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]
    parts = []
    sentences = re.split(r'(?<=[。！？.!?\n])', text)
    current = []
    current_len = 0
    for sent in sentences:
        if not sent:
            continue
        if current and current_len + len(sent) > max_chars:
            parts.append(''.join(current))
            current = [sent]
            current_len = len(sent)
        else:
            current.append(sent)
            current_len += len(sent)
    if current:
        parts.append(''.join(current))
    if any(len(p) > max_chars for p in parts):
        final = []
        for p in parts:
            while len(p) > max_chars:
                final.append(p[:max_chars])
                p = p[max_chars:]
            if p:
                final.append(p)
        parts = final
    return parts


def _split_by_headings(text, fenced_ranges):
    """Split text into (level, title, content) tuples."""
    headings = [(m.start(), len(m.group(1)), m.group(2), m.end())
                for m in _HEADING.finditer(text) if not _in_fence(m.start(), fenced_ranges)]

    if not headings:
        return []

    result = []
    if headings[0][0] > 0:
        preamble = text[:headings[0][0]].strip()
        if preamble:
            result.append((None, '', preamble))

    for i, (start, level, title, end) in enumerate(headings):
        next_start = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        content = text[end:next_start]
        result.append((level, title, content))

    return result
