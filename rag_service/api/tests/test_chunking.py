from __future__ import annotations

from app.chunking import chunk_text, normalize_text


def test_normalize_collapses_pdf_artifacts() -> None:
    raw = "Hola  mundo\f-- 1 of 3 --\n\nPágina 2 de 3\nText\to\n"
    cleaned = normalize_text(raw)
    assert "\f" not in cleaned
    assert "1 of 3" not in cleaned
    assert "Página 2 de 3" not in cleaned
    assert "  " not in cleaned


def test_chunks_respect_max_size() -> None:
    text = " ".join(f"palabra{i}" for i in range(400))
    chunks = chunk_text(text, chunk_size=200, overlap=20)
    assert chunks
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("   \n\n  ") == []


def test_sections_split_on_paragraphs() -> None:
    text = "SECCIÓN A\n\nContenido de A.\n\nSECCIÓN B\n\nContenido de B."
    chunks = chunk_text(text, chunk_size=600, overlap=0)
    assert 1 <= len(chunks) <= 2
    assert "SECCIÓN A" in " ".join(chunks)
