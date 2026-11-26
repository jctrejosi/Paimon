from __future__ import annotations

import pytest

from app.extraction import ExtractionError, extract_file_bytes


def test_plain_text() -> None:
    result = extract_file_bytes(b"Hola mundo", "nota.txt")
    assert "Hola mundo" in result.text


def test_csv_is_readable() -> None:
    result = extract_file_bytes(b"Planta,Temp\nTomate,24\n", "catalogo.csv")
    assert "Tomate | 24" in result.text


def test_html_strips_tags() -> None:
    result = extract_file_bytes(b"<h1>Lechuga</h1><p>Fria</p>", "doc.html")
    assert "Lechuga" in result.text
    assert "<h1>" not in result.text


def test_json_is_pretty_printed() -> None:
    result = extract_file_bytes(b'{"planta":"tomate","temp":24}', "d.json")
    assert '"planta"' in result.text


def test_empty_file_raises() -> None:
    with pytest.raises(ExtractionError):
        extract_file_bytes(b"   ", "vacio.txt")
