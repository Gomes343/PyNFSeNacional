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


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 502, 503])
def test_falha_nao_vira_inexistente(client, monkeypatch, status):
    _capturar(client, monkeypatch, FakeResp(status_code=status,
                                            payload={"mensagem": "qualquer"}))
    with pytest.raises(RuntimeError, match=str(status)):
        client.parametros_convenio("3555406")
    with pytest.raises(RuntimeError, match=str(status)):
        client.aliquotas("3555406", "07.11.01.000", "2026-11-01")


@pytest.mark.parametrize("status", [200, 404])
def test_corpo_nao_json_nao_vira_inexistente(client, monkeypatch, status):
    _capturar(client, monkeypatch, FakeResp(status_code=status, text="<html>"))
    with pytest.raises(RuntimeError, match="não-JSON"):
        client.parametros_convenio("3555406")
    with pytest.raises(RuntimeError, match="não-JSON"):
        client.aliquotas("3555406", "07.11.01.000", "2026-11-01")


def test_404_sem_a_resposta_do_adn_levanta(client, monkeypatch):
    """Um 404 que não é o "não encontrado" do ADN (rota errada, intermediário) é "não sei"."""
    _capturar(client, monkeypatch, FakeResp(status_code=404, payload={"error": "Not Found"}))
    with pytest.raises(RuntimeError, match="404"):
        client.parametros_convenio("3555406")
    with pytest.raises(RuntimeError, match="404"):
        client.aliquotas("3555406", "07.11.01.000")


def test_mensagem_do_adn_fica_no_cliente(client, monkeypatch):
    _capturar(client, monkeypatch, FakeResp(status_code=404, payload={
        "parametrosConvenio": None, "mensagem": "Convênio para o município não encontrado."}))
    assert client.parametros_convenio("9999999") is None
    assert client.ultima_mensagem_adn == "Convênio para o município não encontrado."


def test_200_sem_parametros_levanta(client, monkeypatch):
    _capturar(client, monkeypatch, FakeResp(payload={"parametrosConvenio": None}))
    with pytest.raises(RuntimeError, match="parametrosConvenio"):
        client.parametros_convenio("3555406")
    _capturar(client, monkeypatch, FakeResp(payload={"mensagem": "ok"}))
    with pytest.raises(RuntimeError, match="aliquotas"):
        client.aliquotas("3555406", "07.11.01.000", "2026-11-01")


@pytest.mark.parametrize("mun", ["", "SAO PAULO", "355540", "35554060"])
def test_municipio_invalido_nao_consulta(client, monkeypatch, mun):
    urls = _capturar(client, monkeypatch, FakeResp(status_code=404, payload={"mensagem": "x"}))
    with pytest.raises(ValueError, match="7 dígitos"):
        client.parametros_convenio(mun)
    with pytest.raises(ValueError, match="7 dígitos"):
        client.aliquotas(mun, "07.11.01.000", "2026-11-01")
    assert urls == []


@pytest.mark.parametrize("cod", ["071101000", "", "07.11.01", "7.11.01.000", "07.11.01.0001"])
def test_codigo_do_servico_fora_do_formato_nao_consulta(client, monkeypatch, cod):
    urls = _capturar(client, monkeypatch, FakeResp(status_code=404, payload={"mensagem": "x"}))
    with pytest.raises(ValueError, match="00.00.00.000"):
        client.aliquotas("3555406", cod, "2026-11-01")
    assert urls == []


@pytest.mark.parametrize("comp", ["01/11/2026", "20261101", "2026-11"])
def test_competencia_fora_do_formato_nao_consulta(client, monkeypatch, comp):
    urls = _capturar(client, monkeypatch, FakeResp(payload={"aliquotas": {}}))
    with pytest.raises(ValueError, match="AAAA-MM-DD"):
        client.aliquotas("3555406", "07.11.01.000", comp)
    assert urls == []


def test_aliquotas_so_do_codigo_pedido(client, monkeypatch):
    _capturar(client, monkeypatch, FakeResp(payload={"aliquotas": {
        "07.11.01.000": [{"Aliq": 2.0}], "07.11.01.001": [{"Aliq": 5.0}]}}))
    assert client.aliquotas("3555406", "07.11.01.000", "2026-11-01") == [{"Aliq": 2.0}]


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
