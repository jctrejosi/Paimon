"""Autenticación por clave: la misma clave llega en UTF-8 o en latin-1.

`curl` y la mayoría de clientes envían la cabecera en UTF-8; los navegadores
(Swagger UI) la envían como ByteString (latin-1). Ambas deben valer.
"""

from app.api_key_auth import accepted_encodings, is_valid_token


def test_acepta_la_misma_clave_en_utf8_y_latin1(monkeypatch):
    monkeypatch.setenv("API_AUTH_REQUIRED", "1")
    monkeypatch.setenv("API_KEYS", "otraclave,Aleja la más linda")

    assert is_valid_token("Aleja la más linda")
    assert is_valid_token("Aleja la más linda".encode("utf-8"))
    assert is_valid_token("Aleja la más linda".encode("latin-1"))
    # Cambiar la tilde no debe colar.
    assert not is_valid_token("Aleja la mas linda")


def test_clave_ascii_tiene_una_sola_forma(monkeypatch):
    assert accepted_encodings("otraclave") == [b"otraclave"]


def test_clave_fuera_de_latin1_solo_utf8(monkeypatch):
    clave = "clave-日本"
    assert accepted_encodings(clave) == [clave.encode("utf-8")]
