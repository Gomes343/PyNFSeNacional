"""Parametrização do município no ADN (convênio e alíquotas) — unidade, SEM rede.

As respostas reproduzem as que o ADN de produção deu (05/11/2026), com o corpo do 404
("não encontrado") que o ADN manda com `mensagem`."""

from __future__ import annotations

import pytest
from test_sefin import FakeResp

from pynfsenacional.sefin import SefinClient


@pytest.fixture
def client(pfx_teste):
    caminho, senha = pfx_teste
    return SefinClient(ambiente="producao", cert_pfx_path=str(caminho), senha=senha)


def _capturar(client, monkeypatch, resp):
    urls = []

    def fake(metodo, url, **kw):
        urls.append((metodo, url))
        return resp

    monkeypatch.setattr(client, "_req_url", fake)
    return urls


def test_convenio_aderente(client, monkeypatch):
    urls = _capturar(client, monkeypatch, FakeResp(payload={
        "parametrosConvenio": {"aderenteAmbienteNacional": 1, "aderenteEmissorNacional": 1},
        "mensagem": "Parâmetros do convênio recuperados com sucesso."}))
    par = client.parametros_convenio("3555406")
    assert par == {"aderenteAmbienteNacional": 1, "aderenteEmissorNacional": 1}
    assert urls == [("GET", "https://adn.nfse.gov.br/parametrizacao/3555406/convenio")]


def test_convenio_inexistente_e_none(client, monkeypatch):
    _capturar(client, monkeypatch, FakeResp(status_code=404, payload={
        "parametrosConvenio": None, "mensagem": "Convênio para o  município não encontrado."}))
    assert client.parametros_convenio("9999999") is None


def test_falha_nao_vira_inexistente(client, monkeypatch):
    _capturar(client, monkeypatch, FakeResp(status_code=503))
    with pytest.raises(RuntimeError, match="503"):
        client.parametros_convenio("3555406")
    with pytest.raises(RuntimeError, match="503"):
        client.aliquotas("3555406", "07.11.01.000", "2026-11-01")


def test_aliquota_na_competencia(client, monkeypatch):
    urls = _capturar(client, monkeypatch, FakeResp(payload={
        "aliquotas": {"07.11.01.000": [
            {"Incidencia": "SIM", "Aliq": 4.0, "DtIni": "2023-12-10T00:00:00", "DtFim": None}]},
        "mensagem": "Alíquotas recuperadas com sucesso."}))
    lista = client.aliquotas("3510500", "07.11.01.000", "2026-11-01")
    assert lista == [{"Incidencia": "SIM", "Aliq": 4.0, "DtIni": "2023-12-10T00:00:00",
                      "DtFim": None}]
    assert urls[0][1] == ("https://adn.nfse.gov.br/parametrizacao/3510500/07.11.01.000/"
                          "2026-11-01T12%3A00%3A00/aliquota")


def test_aliquota_sem_competencia_le_o_historico(client, monkeypatch):
    urls = _capturar(client, monkeypatch, FakeResp(payload={"aliquotas": {}}))
    assert client.aliquotas("3510500", "07.11.01.000") == []
    assert urls[0][1].endswith("/3510500/07.11.01.000/historicoaliquotas")


def test_aliquota_nao_administrada_e_lista_vazia(client, monkeypatch):
    _capturar(client, monkeypatch, FakeResp(status_code=404, payload={
        "aliquotas": None, "mensagem": "Alíquotas não encontradas."}))
    assert client.aliquotas("3555406", "99.99.99.999", "2026-11-01") == []
