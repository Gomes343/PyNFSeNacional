"""Fase 3: leitura do certificado A1 (.pfx).

CI: usa um .pfx self-signed descartável (cifra moderna) — sem segredo, reproduzível.
Local: o teste `requires_cert` lê um .pfx REAL (ex.: o da GT) via env var, validando
o caminho de cifra legada ICP-Brasil (§9) — pulado no CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pynfsenacional.certificado import Certificado, CertificadoError
from pynfsenacional.config import Certificado as CertConfig


def test_carregar_pfx_teste(pfx_teste):
    caminho, senha = pfx_teste
    cert = Certificado(CertConfig(path=str(caminho), senha=senha)).carregar()
    assert cert.titular.startswith("TESTE PYNFSE")
    assert cert.cnpj == "11222333000181"        # extraído do CN 'NOME:DOC'
    assert cert.validade.year == 2028            # inicio 2026-01-01 + 730 dias
    assert not cert.legado                       # cifra moderna, sem fallback


def test_senha_errada_da_erro_claro(pfx_teste):
    caminho, _ = pfx_teste
    cert = Certificado(CertConfig(path=str(caminho), senha="senha-errada"))
    with pytest.raises(CertificadoError) as exc:
        cert.carregar()
    # a mensagem NÃO pode afirmar "senha errada" categoricamente (§9)
    assert "cifra" in str(exc.value).lower() or "legada" in str(exc.value).lower()


def test_arquivo_inexistente(tmp_path):
    cfg = CertConfig(path=str(tmp_path / "nao_existe.pfx"), senha="x")
    with pytest.raises(CertificadoError, match="não encontrado"):
        Certificado(cfg).carregar()


def test_como_pem(pfx_teste, tmp_path):
    caminho, senha = pfx_teste
    cert = Certificado(CertConfig(path=str(caminho), senha=senha)).carregar()
    cert_pem, key_pem = cert.como_pem(tmp_path / "pem")
    assert Path(cert_pem).read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    assert b"PRIVATE KEY" in Path(key_pem).read_bytes()


@pytest.mark.requires_cert
def test_pfx_real_icp_brasil():
    """Lê um .pfx REAL (ex.: o da GT) — valida o caminho de cifra legada ICP-Brasil.
    Defina PYNFSE_TEST_PFX e PYNFSE_TEST_PFX_SENHA p/ rodar localmente."""
    caminho = os.environ.get("PYNFSE_TEST_PFX")
    senha = os.environ.get("PYNFSE_TEST_PFX_SENHA")
    if not caminho or not senha:
        pytest.skip("defina PYNFSE_TEST_PFX e PYNFSE_TEST_PFX_SENHA")
    cert = Certificado(CertConfig(path=caminho, senha=senha)).carregar()
    assert cert.cnpj and len(cert.cnpj) in (11, 14)
    print(f"\n  titular={cert.titular!r} validade={cert.validade.date()} legado={cert.legado}")
