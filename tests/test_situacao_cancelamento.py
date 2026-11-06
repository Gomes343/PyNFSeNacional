"""O E0840 não prova cancelamento: `situacao_cancelamento` pergunta à SEFIN pelos eventos.
Respostas reproduzem as da SEFIN de homologação (06/11/2026): 200 com `eventos`, 404 com JSON
para evento inexistente e 404 em HTML para rota desconhecida. SEM rede."""

from __future__ import annotations

import pytest
from test_sefin import FakeResp

from pynfsenacional import sefin
from pynfsenacional.sefin import SefinClient

CHAVE = "3304557" + "2" + "2" + "11222333000181" + "0000000000147" + "2610" + "123456789" + "0"
_EXISTE = {"tipoAmbiente": 2, "eventos": [{"chaveAcesso": CHAVE, "tipoEvento": 101103,
                                           "numeroPedidoRegistroEvento": 1}]}
_NAO = {"tipoAmbiente": 2, "versaoAplicativo": "SefinNacional_1.6.0"}


@pytest.fixture
def client(pfx_teste):
    caminho, senha = pfx_teste
    return SefinClient(ambiente="homologacao", cert_pfx_path=str(caminho), senha=senha)


def _servir(client, monkeypatch, existentes, erro=None):
    urls = []

    def fake(metodo, url, **kw):
        urls.append(url)
        if erro is not None:
            return erro
        tipo = url.rstrip("/").split("/")[-2]
        return FakeResp(payload=_EXISTE) if tipo in existentes else FakeResp(404, payload=_NAO)

    monkeypatch.setattr(client, "_req_url", fake)
    return urls


def test_evento_registrado_le_a_rota_com_tipo_e_sequencial(client, monkeypatch):
    urls = _servir(client, monkeypatch, {"101103"})
    assert client.evento_registrado(CHAVE, "101103") is True
    assert client.evento_registrado(CHAVE, "101101") is False
    assert urls[0].endswith(f"/nfse/{CHAVE}/eventos/101103/1")


@pytest.mark.parametrize("resp", [FakeResp(404, text="<html>404</html>"), FakeResp(500),
                                  FakeResp(429, payload={}), FakeResp(200, payload={"x": 1})])
def test_evento_registrado_sem_saber_levanta(client, monkeypatch, resp):
    _servir(client, monkeypatch, set(), erro=resp)
    with pytest.raises(RuntimeError):
        client.evento_registrado(CHAVE, "101101")


@pytest.mark.parametrize("existentes, esperado", [
    ({"101101"}, sefin.CANCELADA),
    ({"101103", "105104"}, sefin.CANCELADA),          # análise deferida
    ({"105102"}, sefin.CANCELADA),                    # substituição
    ({"305101"}, sefin.CANCELADA),                    # por ofício
    ({"101103"}, sefin.EM_ANALISE),                   # o caso medido em homologação
    ({"101103", "105105"}, sefin.INDEFERIDA),
    (set(), sefin.SEM_CANCELAMENTO),
])
def test_situacao_cancelamento(client, monkeypatch, existentes, esperado):
    _servir(client, monkeypatch, existentes)
    assert client.situacao_cancelamento(CHAVE) == esperado


def test_conferir_e0840_em_analise_nao_diz_cancelada(client, monkeypatch):
    _servir(client, monkeypatch, {"101103"})
    sit, msg = sefin.conferir_e0840(client, CHAVE)
    assert sit == sefin.EM_ANALISE and "NÃO está cancelada" in msg


def test_conferir_e0840_com_falha_e_nao_sei(client, monkeypatch):
    _servir(client, monkeypatch, set(), erro=FakeResp(503))
    sit, msg = sefin.conferir_e0840(client, CHAVE)
    assert sit is None and "NÃO SEI" in msg
