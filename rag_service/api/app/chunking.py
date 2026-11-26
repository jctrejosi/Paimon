"""Troceado de texto del servicio RAG.

1. `normalize_text()` limpia artefactos de extracción.
2. Secciones hasta `chunk_size`; las mayores se reparten por oraciones/palabras.
3. Los chunks diminutos se fusionan con un vecino.
4. El solape se aplica en límite de palabra.
"""

import re

DEFAULT_CHUNK_SIZE = 600
DEFAULT_OVERLAP = 100

_PAGE_MARKER_RE = re.compile(
    r"-{2,}[ \t]*\d+[ \t]+(?:of|de)[ \t]+\d+[ \t]*-{2,}", re.IGNORECASE
)
_PAGE_LINE_RE = re.compile(
    r"^[ \t]*(?:p[áa]gina|page)[ \t]+\d+[ \t]*(?:de|of|/)[ \t]*\d+[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def normalize_text(text: str) -> str:
    text = str(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\f", "\n")
    text = _PAGE_MARKER_RE.sub(" ", text)
    text = _PAGE_LINE_RE.sub("", text)
    text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_heading(section: str) -> bool:
    return len(section) < 120 and (section.isupper() or section.rstrip().endswith(":"))


def _tail_at_word_boundary(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    tail = text[-max_chars:]
    first_space = re.search(r"\s", tail)
    if first_space:
        return tail[first_space.start() + 1 :]
    return tail


def _split_by_words(text: str, max_len: int) -> list[str]:
    out: list[str] = []
    buf = ""
    for word in text.split():
        if len(word) > max_len:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(word[i : i + max_len] for i in range(0, len(word), max_len))
            continue
        cand = f"{buf} {word}" if buf else word
        if len(cand) <= max_len:
            buf = cand
        else:
            if buf:
                out.append(buf)
            buf = word
    if buf:
        out.append(buf)
    return out


def _split_long_piece(piece: str, max_len: int) -> list[str]:
    out: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf:
            out.append(buf)
            buf = ""

    for sentence in re.split(r"(?<=[.!?])\s+", piece):
        if len(sentence) > max_len:
            flush()
            out.extend(_split_by_words(sentence, max_len))
            continue
        cand = f"{buf} {sentence}" if buf else sentence
        if len(cand) <= max_len:
            buf = cand
        else:
            flush()
            buf = sentence
    flush()
    return out


def _attach_headings(pieces: list[str], max_chars: int) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    i = 0
    while i < len(pieces):
        piece = pieces[i]
        if (
            _is_heading(piece)
            and i + 1 < len(pieces)
            and not _is_heading(pieces[i + 1])
        ):
            nxt = pieces[i + 1]
            room = max_chars - len(piece) - 2
            if room > 0:
                if len(nxt) <= room:
                    out.append((f"{piece}\n\n{nxt}", True))
                    i += 2
                    continue
                parts = _split_long_piece(nxt, room)
                if parts:
                    out.append((f"{piece}\n\n{parts[0]}", True))
                    out.extend((p, False) for p in parts[1:])
                    i += 2
                    continue
        out.append((piece, _is_heading(piece)))
        i += 1
    return out


def _merge_tiny(raw: list[str], min_chars: int, max_merge: int) -> list[str]:
    i = 0
    while i < len(raw):
        if len(raw) == 1:
            break
        if len(raw[i]) >= min_chars:
            i += 1
            continue
        if i > 0 and len(raw[i - 1]) + len(raw[i]) + 2 <= max_merge:
            raw[i - 1] = f"{raw[i - 1]}\n\n{raw[i]}"
            raw.pop(i)
            i = max(0, i - 1)
            continue
        if i + 1 < len(raw) and len(raw[i]) + len(raw[i + 1]) + 2 <= max_merge:
            raw[i] = f"{raw[i]}\n\n{raw[i + 1]}"
            raw.pop(i + 1)
            continue
        i += 1
    return raw


def chunk_by_sections(
    text: str,
    max_chars: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    clean = normalize_text(text)
    if not clean:
        return []

    max_chars = max(1, max_chars)
    overlap = max(0, min(overlap, max_chars // 2))
    budget = max(1, max_chars - overlap - (4 if overlap > 0 else 0))

    pieces: list[str] = []
    for section in re.split(r"\n{2,}", clean):
        section = section.strip()
        if not section:
            continue
        if len(section) <= budget:
            pieces.append(section)
        else:
            pieces.extend(_split_long_piece(section, budget))

    if not pieces:
        return []

    marked = _attach_headings(pieces, budget)

    raw: list[str] = []
    buf = ""
    for piece, opens_section in marked:
        if opens_section and buf:
            raw.append(buf)
            buf = piece
            continue

        cand = f"{buf}\n\n{piece}" if buf else piece
        if len(cand) <= budget:
            buf = cand
        else:
            if buf:
                raw.append(buf)
            if len(piece) > budget:
                raw.extend(_split_long_piece(piece, budget))
                buf = ""
            else:
                buf = piece
    if buf:
        raw.append(buf)

    min_chars = max(1, round(budget * 0.45))
    raw = _merge_tiny(raw, min_chars, budget)

    chunks: list[str] = []
    for i, current in enumerate(raw):
        if i > 0 and overlap > 0:
            snippet = _tail_at_word_boundary(raw[i - 1], overlap).strip()
            if snippet:
                current = f"...{snippet} {current}"
        current = current.strip()
        if current:
            chunks.append(current)

    return chunks


def chunk_by_fixed_size(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    clean = normalize_text(text)
    if not clean:
        return []

    chunk_size = max(1, chunk_size)
    overlap = max(0, min(overlap, chunk_size // 2))

    chunks: list[str] = []
    start = 0

    while start < len(clean):
        end = min(start + chunk_size, len(clean))
        if end < len(clean):
            for sep in ("\n\n", "\n", ". ", " "):
                pos = clean.rfind(sep, start, end)
                if pos > start + chunk_size // 2:
                    end = pos + len(sep)
                    break

        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(clean):
            break
        start = max(end - overlap, start + 1)

    return chunks


def chunk_text(
    text: str,
    strategy: str = "sections",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    if strategy == "fixed":
        return chunk_by_fixed_size(text, chunk_size, overlap)
    return chunk_by_sections(text, max_chars=chunk_size, overlap=overlap)
