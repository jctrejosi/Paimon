from __future__ import annotations

import io
import shutil
import zipfile
import xml.etree.ElementTree as ET

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


def test_json_is_readable() -> None:
    result = extract_file_bytes(b'{"planta":"tomate","temp":24}', "d.json")
    assert '"planta"' in result.text


def test_rtf() -> None:
    data = b"{\\rtf1\\ansi\\deff0 Hola RTF\\par segunda linea}"
    result = extract_file_bytes(data, "doc.rtf")
    assert "Hola RTF" in result.text
    assert "segunda linea" in result.text


def test_odt() -> None:
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        "<office:body><office:text>"
        "<text:p>Hola ODT tomate</text:p>"
        "</office:text></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("content.xml", content)
    result = extract_file_bytes(buffer.getvalue(), "doc.odt")
    assert "tomate" in result.text.lower()


def test_zip_archive() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("nota.txt", "Dentro del zip")
    result = extract_file_bytes(buffer.getvalue(), "paquete.zip")
    assert "Dentro del zip" in result.text


def test_pptx() -> None:
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    textbox = slide.shapes.add_textbox(0, 0, 300, 100)
    textbox.text_frame.text = "Diapositiva del tomate"
    buffer = io.BytesIO()
    prs.save(buffer)
    result = extract_file_bytes(buffer.getvalue(), "slides.pptx")
    assert "tomate" in result.text.lower()


def test_pdf_text_layer() -> None:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "El tomate necesita 24 C")
    data = doc.tobytes()
    doc.close()
    result = extract_file_bytes(data, "catalogo.pdf")
    assert "tomate" in result.text.lower()


def test_empty_file_raises() -> None:
    with pytest.raises(ExtractionError):
        extract_file_bytes(b"   ", "vacio.txt")


@pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract no está instalado"
)
def test_pdf_ocr() -> None:
    fitz = pytest.importorskip("fitz")
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (800, 200), "white")
    ImageDraw.Draw(image).text((20, 80), "TOMATE 24 GRADOS", fill="black")
    png = io.BytesIO()
    image.save(png, format="PNG")

    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(0, 0, 800, 200), stream=png.getvalue())
    data = doc.tobytes()
    doc.close()

    result = extract_file_bytes(data, "escaneado.pdf")
    assert "TOMATE" in result.text.upper()


# Evita el aviso de import no usado en linters estrictos.
_ = ET
