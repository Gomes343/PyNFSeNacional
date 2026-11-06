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


# ── quem é o titular: CNPJ × CPF, CN sem ':' e a SAN ICP-Brasil ──────────────────────────────
def _abrir(tmp_path, nome="c.pfx", senha="0000", **kw):
    from conftest import gerar_pfx_teste
    caminho = tmp_path / nome
    caminho.write_bytes(gerar_pfx_teste(senha, **kw))
    return Certificado(CertConfig(path=str(caminho), senha=senha)).carregar()


def test_ecnpj_e_inequivoco(pfx_teste):
    caminho, senha = pfx_teste
    cert = Certificado(CertConfig(path=str(caminho), senha=senha)).carregar()
    assert cert.documento == cert.cnpj == "11222333000181"
    assert cert.tipo_documento == "CNPJ"


def test_ecpf_nao_passa_por_ecnpj(tmp_path):
    """O e-CPF do sócio NÃO é o certificado da empresa: `cnpj` (o nome antigo) devolve o CPF,
    e é o `tipo_documento` que separa os dois."""
    cert = _abrir(tmp_path, cn="FULANO DE TAL:11144477735")
    assert cert.documento == "11144477735"
    assert cert.tipo_documento == "CPF"


def test_cnpj_alfanumerico_e_cnpj(tmp_path):
    assert _abrir(tmp_path, cn="EMPRESA:12ABC34501DE35").tipo_documento == "CNPJ"


def test_cn_sem_dois_pontos_acha_o_cnpj_no_cn(tmp_path):
    cert = _abrir(tmp_path, cn="EMPRESA FICTICIA LTDA 11222333000181")
    assert cert.documento == "11222333000181" and cert.tipo_documento == "CNPJ"


def test_cn_sem_dois_pontos_ignora_numero_que_nao_e_cnpj(tmp_path):
    # 14 dígitos com DV errado não são CNPJ; sem SAN, não há documento
    cert = _abrir(tmp_path, cn="EMPRESA FICTICIA LTDA 11222333000199")
    assert cert.documento is None and cert.tipo_documento is None


def test_cnpj_so_na_san(tmp_path):
    from conftest import san_icp
    cert = _abrir(tmp_path, cn="EMPRESA FICTICIA LTDA",
                  san=[san_icp("2.16.76.1.3.3", "11222333000181")])
    assert cert.documento == "11222333000181" and cert.tipo_documento == "CNPJ"


def test_cpf_so_na_san_de_pessoa_fisica(tmp_path):
    from conftest import san_icp
    # 2.16.76.1.3.1: nascimento (DDMMAAAA) + CPF + NIS + RG + órgão — dados fictícios
    cert = _abrir(tmp_path, cn="FULANO DE TAL",
                  san=[san_icp("2.16.76.1.3.1", "01011980" + "11144477735" + "0" * 11)])
    assert cert.documento == "11144477735" and cert.tipo_documento == "CPF"


def test_der_conteudo_tolera_lixo():
    from pynfsenacional.certificado import _der_conteudo
    assert _der_conteudo(b"") is None and _der_conteudo(b"\x04\x09abc") is None
    assert _der_conteudo(b"\xa0\x05\x04\x03abc") == b"abc"         # [0] explícito aberto
    assert _der_conteudo(b"\x04\x81\x03abc") == b"abc"              # tamanho na forma longa


# ── fallback legado: a senha nunca na linha de comando; o material segue adiante ─────────────
class _Proc:
    def __init__(self, stdout):
        self.stdout, self.stderr, self.returncode = stdout, b"", 0


def _pem_de(pfx: bytes, senha: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    p = pkcs12.load_pkcs12(pfx, senha)
    return (p.cert.certificate.public_bytes(serialization.Encoding.PEM)
            + p.key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))


def _forcar_legado(monkeypatch, pfx: bytes, senha: str, chamadas: list):
    """A `cryptography` "não lê" o arquivo original (como num RC2-40 sem provedor legado) e o
    `openssl` falso devolve o PEM — registrando com o que foi chamado."""
    from cryptography.hazmat.primitives.serialization import pkcs12

    from pynfsenacional import certificado as mod
    original = pkcs12.load_pkcs12
    pem = _pem_de(pfx, senha.encode())

    def load(data, pw, *a, **k):
        if data == pfx:
            raise ValueError("Could not deserialize PKCS12 data (simulado)")
        return original(data, pw, *a, **k)

    def run(argv, **kw):
        chamadas.append((list(argv), kw))
        return _Proc(pem)

    monkeypatch.setattr(mod.pkcs12, "load_pkcs12", load)
    monkeypatch.setattr(mod.shutil, "which", lambda nome: "/usr/bin/openssl")
    monkeypatch.setattr(mod.subprocess, "run", run)


def test_legado_senha_vai_pelo_stdin_nunca_no_argv(tmp_path, monkeypatch):
    from conftest import gerar_pfx_teste
    senha = "S3nh@-do-teste"
    pfx = gerar_pfx_teste(senha)
    caminho = tmp_path / "legado.pfx"
    caminho.write_bytes(pfx)
    chamadas: list = []
    _forcar_legado(monkeypatch, pfx, senha, chamadas)
    cert = Certificado(CertConfig(path=str(caminho), senha=senha)).carregar()
    assert cert.legado and cert.tipo_documento == "CNPJ"
    (argv, kw), = chamadas
    assert not any(senha in a for a in argv)                  # /proc/<pid>/cmdline limpo
    assert "-passin" in argv and argv[argv.index("-passin") + 1] == "stdin"
    assert kw["input"] == senha.encode() + b"\n"
    assert "-out" not in argv                                  # o PEM volta pelo stdout


def test_legado_pkcs12_bytes_e_o_reembalado(tmp_path, monkeypatch):
    """A assinatura e o mTLS recebem o MESMO material que o objeto abriu: o .pfx reembalado,
    que a `cryptography` lê com a mesma senha — não o arquivo original."""
    from conftest import gerar_pfx_teste
    from cryptography.hazmat.primitives.serialization import pkcs12
    senha = "0000"
    pfx = gerar_pfx_teste(senha)
    caminho = tmp_path / "legado.pfx"
    caminho.write_bytes(pfx)
    _forcar_legado(monkeypatch, pfx, senha, [])
    cert = Certificado(CertConfig(path=str(caminho), senha=senha)).carregar()
    novo = cert.pkcs12_bytes()
    assert novo != pfx
    assert pkcs12.load_pkcs12(novo, senha.encode()).cert is not None


def test_moderno_pkcs12_bytes_e_o_proprio_arquivo(pfx_teste):
    caminho, senha = pfx_teste
    cert = Certificado(CertConfig(path=str(caminho), senha=senha)).carregar()
    assert cert.pkcs12_bytes() == Path(caminho).read_bytes()


def test_legado_com_openssl_de_verdade_nao_poe_a_senha_no_argv(pfx_teste, monkeypatch):
    """Com o binário real (quando há um com `-legacy`): a recuperação funciona pelo stdin."""
    import shutil
    import subprocess

    from pynfsenacional import certificado as mod
    if not shutil.which("openssl"):
        pytest.skip("sem openssl")
    caminho, senha = pfx_teste
    real = subprocess.run
    vistos: list = []

    def espiao(argv, **kw):
        vistos.append(list(argv))
        return real(argv, **kw)

    monkeypatch.setattr(mod.subprocess, "run", espiao)
    obj = Certificado(CertConfig(path=str(caminho), senha=senha))
    rec = obj._tentar_legado(Path(caminho).read_bytes(), senha.encode())
    if rec is None:
        pytest.skip("este openssl não tem -legacy")
    assert vistos and not any(senha in a for a in vistos[0])
