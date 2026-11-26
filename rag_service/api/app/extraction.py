"""Extracción de texto de documentos para el RAG.

Formatos:
- Texto sin dependencias: `.txt`, `.md`, `.csv`, `.tsv`, `.json`, `.log`, `.xml`,
  `.yaml`, `.yml`, `.ini`, `.rst`.
- HTML (`.html`, `.htm`): se eliminan las etiquetas.
- PDF (`.pdf`): requiere `pypdf` (importación perezosa).
- DOCX (`.docx`): requiere `python-docx`.
- XLSX/XLSM (`.xlsx`, `.xlsm`): requiere `openpyxl`.

Las dependencias opcionales se importan solo al procesar ese formato; si faltan,
se lanza un `ExtractionError` claro.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from html.parser import HTMLParser
from typing import ClassVar


class ExtractionError(ValueError):
    """No se pudo extraer texto del archivo."""


_TEXT_EXTENSIONS = {
    "",
    ".txt",
    ".text",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".ini",
}

_HTML_EXTENSIONS = {".html", ".htm"}


class ExtractionResult:
    def __init__(self, text: str, pages: list[str], metadata: dict | None = None):
        self.text = text
        self.pages = pages
        self.metadata = metadata or {}

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


class _HTMLTextExtractor(HTMLParser):
    _BLOCK_TAGS: ClassVar[set[str]] = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "table", "td", "th", "ul", "ol",
    }

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r" *\n *", "\n", raw)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def _strip_html(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def _extract_pdf(data: bytes) -> tuple[str, list[str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("Para leer PDFs instala 'pypdf'.") from exc

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages), pages


def _extract_docx(data: bytes) -> str:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("Para leer DOCX instala 'python-docx'.") from exc

    document = docx.Document(io.BytesIO(data))
    blocks = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                blocks.append(" | ".join(cells))
    return "\n\n".join(blocks)


def _extract_xlsx(data: bytes) -> str:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("Para leer XLSX instala 'openpyxl'.") from exc

    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheets: list[str] = []
    for sheet in workbook.worksheets:
        rows: list[str] = []
        for row in sheet.iter_rows(values_only=True):
            cells = [str(value).strip() if value is not None else "" for value in row]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            sheets.append(f"# {sheet.title}\n" + "\n".join(rows))
    workbook.close()
    return "\n\n".join(sheets)


def _normalize_json(text: str) -> str:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _normalize_delimited(text: str) -> str:
    first_line = text.splitlines()[0] if text else ""
    delimiter = "\t" if first_line.count("\t") > first_line.count(",") else ","
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = [" | ".join(cell.strip() for cell in row) for row in reader]
    except csv.Error:
        return text
    return "\n".join(rows)


def extract_file_bytes(data: bytes, filename: str) -> ExtractionResult:
    """Extrae texto de los bytes de un archivo según su extensión."""
    ext = os.path.splitext(filename or "")[1].lower()

    pages: list[str] = []
    if ext == ".pdf":
        text, pages = _extract_pdf(data)
    elif ext == ".docx":
        text = _extract_docx(data)
    elif ext in {".xlsx", ".xlsm"}:
        text = _extract_xlsx(data)
    elif ext in _HTML_EXTENSIONS:
        text = _strip_html(_decode_text(data))
    elif ext == ".json":
        text = _normalize_json(_decode_text(data))
    elif ext in {".csv", ".tsv"}:
        text = _normalize_delimited(_decode_text(data))
    else:
        text = _decode_text(data)

    if not text or not text.strip():
        raise ExtractionError(
            f"no se pudo extraer texto de '{filename}' (puede estar escaneado, "
            "vacío o ser un formato binario no soportado)"
        )

    return ExtractionResult(text=text, pages=pages or [text], metadata={"extension": ext})
