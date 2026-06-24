"""Fase 6: geração local do DANFSe (danfse.py).

CI: mocka a `BrazilFiscalReport` (a render real precisa de um XML de NFS-e completo,
que carrega dado de cliente — não vai para o git). Local: se PYNFSE_TEST_NFSE_XML
apontar para um XML de NFS-e real, renderiza de verdade e checa o PDF.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pynfsenacional import danfse
from pynfsenacional.emissor import Nota


def test_render_wira_a_lib(monkeypatch, tmp_path):
    capturado = {}

    class FakeDanfse:
        def __init__(self, xml):
            capturado["xml"] = xml

        def output(self, path):
            capturado["out"] = path
            Path(path).write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr("brazilfiscalreport.danfse.Danfse", FakeDanfse)
    destino = tmp_path / "sub" / "nota.pdf"        # subdir inexistente: render deve criar
    out = danfse.render("<NFSe>conteudo</NFSe>", destino)

    assert capturado["xml"] == "<NFSe>conteudo</NFSe>"
    assert Path(out).read_bytes().startswith(b"%PDF")


def test_nota_danfse_sem_xml_levanta():
    nota = Nota(status="ok", emitida=True, id_cliente="x", nfse_xml=None)
    with pytest.raises(ValueError, match="sem XML"):
        nota.danfse("/tmp/x.pdf")


def test_nota_danfse_usa_render(monkeypatch, tmp_path):
    monkeypatch.setattr(danfse, "render", lambda xml, dest: f"RENDER({dest})")
    nota = Nota(status="ok", emitida=True, id_cliente="x", nfse_xml="<NFSe/>")
    assert nota.danfse(tmp_path / "n.pdf") == f"RENDER({tmp_path / 'n.pdf'})"
    assert nota.pdf_path is not None


@pytest.mark.skipif(not os.environ.get("PYNFSE_TEST_NFSE_XML"),
                    reason="defina PYNFSE_TEST_NFSE_XML p/ renderizar um DANFSe real")
def test_render_real(tmp_path):
    xml = Path(os.environ["PYNFSE_TEST_NFSE_XML"]).read_text(encoding="utf-8")
    pdf = danfse.render(xml, tmp_path / "real.pdf")
    data = Path(pdf).read_bytes()
    assert data[:4] == b"%PDF" and len(data) > 2000
