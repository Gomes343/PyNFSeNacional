"""Fase 5: transporte mTLS ao SEFIN (sefin.py) — unidade, SEM rede.

Mocka o `_req` do SefinClient (a única borda de I/O), exercitando o empacotamento
gzip+base64, o parse da resposta (sucesso/erro/idempotência) e a resolução de endpoint.
"""

from __future__ import annotations

import base64
import gzip

import pytest

from pynfsenacional import sefin
from pynfsenacional.sefin import RespostaSefin, SefinClient, resolver_endpoint


class FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("sem JSON")
        return self._payload


def _nfse_b64(nNFSe="1", chave="35000000000000000000000000000000000011222333000181"):
    # dados 100% FICTÍCIOS (CNPJ de teste 11222333000181); a chave não é asserida diretamente.
    xml = f"<NFSe><infNFSe><nNFSe>{nNFSe}</nNFSe><chNFSe>{chave}</chNFSe></infNFSe></NFSe>"
    return base64.b64encode(gzip.compress(xml.encode())).decode()


@pytest.fixture
def client(pfx_teste):
    caminho, senha = pfx_teste
    return SefinClient(ambiente="homologacao", cert_pfx_path=str(caminho), senha=senha)


# ── resolução de endpoint ────────────────────────────────────────────────────
def test_resolver_endpoint():
    assert resolver_endpoint("producao").endswith("sefin.nfse.gov.br/SefinNacional")
    assert "producaorestrita" in resolver_endpoint("homologacao")
    assert "catanduva" in resolver_endpoint("homologacao", "3511102")   # override município
    with pytest.raises(ValueError):
        resolver_endpoint("xpto")


# ── empacotamento + envio ────────────────────────────────────────────────────
def test_emitir_empacota_gzip_b64(client, monkeypatch):
    capturado = {}

    def fake_req(metodo, caminho, **kw):
        capturado["metodo"] = metodo
        capturado["caminho"] = caminho
        capturado["json"] = kw.get("json")
        return FakeResp(payload={"chaveAcesso": "33ABC", "nfseXmlGZipB64": _nfse_b64()})

    monkeypatch.setattr(client, "_req", fake_req)
    resp = client.emitir("<DPS>conteudo</DPS>")

    assert capturado["metodo"] == "POST" and capturado["caminho"] == "nfse"
    # o campo dpsXmlGZipB64 descomprime de volta ao XML enviado
    b64 = capturado["json"]["dpsXmlGZipB64"]
    assert gzip.decompress(base64.b64decode(b64)).decode() == "<DPS>conteudo</DPS>"
    assert resp.ok and resp.chave_acesso == "33ABC" and resp.numero_nfse == "1"


def test_emitir_erro_mapeia_ecode(client, monkeypatch):
    payload = {"erros": [{"codigo": "E0312", "descricao": "código não administrado",
                          "complemento": "pelo município"}]}
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(status_code=400, payload=payload))
    resp = client.emitir("<DPS/>")
    assert not resp.ok
    assert resp.erro_codigo == "E0312"
    assert "não administrado" in resp.erro_msg


def test_emitir_erro_singular_e_maiusculas(client, monkeypatch):
    # o SEFIN alterna `erro` (singular) e subcampos em Maiúsculas
    payload = {"erro": [{"Codigo": "E0008", "Descricao": "data posterior"}]}
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(payload=payload))
    resp = client.emitir("<DPS/>")
    assert resp.erro_codigo == "E0008" and not resp.ok


def test_verificar_dps(client, monkeypatch):
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(status_code=200))
    assert client.verificar_dps("DPS123") is True
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(status_code=404))
    assert client.verificar_dps("DPS123") is False


def test_consultar_dps_devolve_chave(client, monkeypatch):
    monkeypatch.setattr(client, "_req",
                        lambda *a, **k: FakeResp(payload={"chaveAcesso": "33XYZ"}))
    assert client.consultar_dps("DPS123") == "33XYZ"


def test_descomprimir_roundtrip():
    assert sefin._descomprimir(_nfse_b64(nNFSe="9")).count("<nNFSe>9</nNFSe>") == 1


def test_resposta_sem_xml_nem_erro(client, monkeypatch):
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(payload={"foo": "bar"}))
    resp: RespostaSefin = client.emitir("<DPS/>")
    assert not resp.ok and "sem XML" in resp.erro_msg
