"""Fase 5: orquestração do Emissor.emitir() ponta-a-ponta, com o SEFIN MOCKADO.

Exercita o pipeline real (validar → montar DPS → assinar com cert de teste) e o
roteamento do resultado (sucesso/idempotência/erro) + o contador de nDPS, sem rede.
"""

from __future__ import annotations

import pytest

from pynfsenacional import ClienteConfig, Emissor
from pynfsenacional.sefin import RespostaSefin


class FakeSefin:
    def __init__(self, *, ja_emitida=False, resp=None, chave="33JA"):
        self.ja_emitida = ja_emitida
        self.resp = resp
        self.chave = chave
        self.emitiu = False

    def verificar_dps(self, idd):
        return self.ja_emitida

    def consultar_dps(self, idd):
        return self.chave

    def emitir(self, xml):
        self.emitiu = True
        assert "<Signature" in xml          # chegou ASSINADO ao transporte
        return self.resp


@pytest.fixture
def emissor(config_dict, pfx_teste, tmp_path):
    caminho, senha = pfx_teste
    config_dict["certificado"] = {"path": str(caminho), "senha": senha}
    return Emissor(ClienteConfig.from_dict(config_dict), out_dir=tmp_path)


def _emitir(emissor, monkeypatch, fake):
    monkeypatch.setattr(emissor, "_sefin_client", lambda: fake)
    return emissor.emitir(valor=150.0, descricao="Servico de teste",
                          tomador={"cpf_cnpj": "11144477735", "nome": "Fulano de Tal"})


def test_emitir_sucesso_e_incrementa_contador(emissor, monkeypatch):
    fake = FakeSefin(resp=RespostaSefin(ok=True, chave_acesso="33OK", numero_nfse="147",
                                        nfse_xml="<NFSe/>"))
    nota = _emitir(emissor, monkeypatch, fake)
    assert nota.emitida and nota.status == "ok"
    assert nota.chave_acesso == "33OK" and nota.numero_nfse == "147"
    assert nota.id_dps.startswith("DPS") and len(nota.id_dps) == 45
    assert fake.emitiu
    # contador: semente "1" → próximo "2" gravado SÓ após sucesso
    arq = emissor.out_dir / f"numero_{emissor.cfg.id}_homologacao.txt"
    assert arq.read_text() == "2"


def test_emitir_idempotente_nao_reemite(emissor, monkeypatch):
    fake = FakeSefin(ja_emitida=True, chave="33JA")
    nota = _emitir(emissor, monkeypatch, fake)
    assert nota.status == "ja_emitida" and nota.emitida
    assert nota.chave_acesso == "33JA"
    assert not fake.emitiu                     # NÃO reemitiu
    assert not (emissor.out_dir / f"numero_{emissor.cfg.id}_homologacao.txt").exists()


def test_emitir_erro_nao_incrementa(emissor, monkeypatch):
    fake = FakeSefin(resp=RespostaSefin(ok=False, erro_codigo="E0312", erro_msg="não administrado"))
    nota = _emitir(emissor, monkeypatch, fake)
    assert nota.status == "erro" and not nota.emitida
    assert "[E0312]" in nota.erro_msg
    assert not (emissor.out_dir / f"numero_{emissor.cfg.id}_homologacao.txt").exists()
