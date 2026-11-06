"""O pedido de evento (cancelamento): o que a SEFIN recusou, o que nem saiu e o que saiu sem
resposta; o prazo total de relógio; o E0840 no Emissor; a chave de outro emitente; o autor
alfanumérico e o teto da justificativa — tudo sem rede."""

from __future__ import annotations

import time

import pytest
import requests
import urllib3
from test_eventos_dfe import CHAVE, JUST, FakeResp, _b64, _pedido

from pynfsenacional import chave, eventos, sefin
from pynfsenacional.config import ConfigError
from pynfsenacional.sefin import AMBIGUO, NAO_ENVIADO, RECUSADO, REGISTRADO, SefinClient


@pytest.fixture
def client(pfx_teste):
    caminho, senha = pfx_teste
    return SefinClient(ambiente="homologacao", cert_pfx_path=str(caminho), senha=senha)


def _levanta(exc):
    def fake(*a, **k):
        raise exc
    return fake


# ── desfechos do registrar_evento ────────────────────────────────────────────
def test_registrado(client, monkeypatch):
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(201, {
        "eventoXmlGZipB64": _b64("<evento/>")}))
    r = client.registrar_evento(CHAVE, "<p/>")
    assert r.ok and r.desfecho == REGISTRADO and not r.ambiguo


def test_recusa_com_ecode(client, monkeypatch):
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(400, {
        "erros": [{"codigo": "E0823", "descricao": "não permitido"}]}))
    r = client.registrar_evento(CHAVE, "<p/>")
    assert not r.ok and r.desfecho == RECUSADO and not r.ambiguo and not r.ja_vinculado


def test_e0840_e_ja_vinculado(client, monkeypatch):
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(400, {
        "erros": [{"codigo": "E0840", "descricao": "já vinculado"}]}))
    r = client.registrar_evento(CHAVE, "<p/>")
    assert not r.ok and r.ja_vinculado and r.desfecho == RECUSADO


@pytest.mark.parametrize("exc", [
    requests.exceptions.ReadTimeout("read timed out"),
    requests.exceptions.ConnectionError(urllib3.exceptions.ProtocolError(
        "Connection aborted.", ConnectionResetError(104, "reset"))),
    requests.exceptions.ChunkedEncodingError("cortada no meio"),
    requests.exceptions.SSLError("bad record mac"),
    sefin.PrazoEsgotado("sem resposta completa em 90 s"),
])
def test_rede_depois_do_envio_e_ambiguo(client, monkeypatch, exc):
    """☠️ Timeout e conexão caída DEPOIS do POST não são "falhou": a SEFIN pode ter
    registrado. Até a 1.6.0 a exceção subia e quem chamava a lia como recusa."""
    monkeypatch.setattr(client, "_req", _levanta(exc))
    r = client.registrar_evento(CHAVE, "<p/>")
    assert not r.ok and r.ambiguo and r.desfecho == AMBIGUO
    assert "pode ter registrado" in r.erro_msg


@pytest.mark.parametrize("exc", [
    requests.exceptions.ConnectTimeout("connect timed out"),
    requests.exceptions.ConnectionError(urllib3.exceptions.MaxRetryError(
        None, "/", urllib3.exceptions.NewConnectionError(None, "recusada"))),
    requests.exceptions.InvalidURL("url"),
])
def test_conexao_que_nao_abriu_e_nao_enviado(client, monkeypatch, exc):
    monkeypatch.setattr(client, "_req", _levanta(exc))
    r = client.registrar_evento(CHAVE, "<p/>")
    assert not r.ok and r.desfecho == NAO_ENVIADO and not r.ambiguo
    assert "nada chegou" in r.erro_msg


@pytest.mark.parametrize("status, payload, desfecho", [
    (502, None, AMBIGUO), (504, None, AMBIGUO), (500, None, AMBIGUO), (408, None, AMBIGUO),
    (200, {}, AMBIGUO), (201, {"outra": 1}, AMBIGUO), (503, {}, AMBIGUO),
    (401, None, RECUSADO), (403, None, RECUSADO), (429, None, RECUSADO), (404, {}, RECUSADO),
])
def test_resposta_sem_corpo_util(client, monkeypatch, status, payload, desfecho):
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(status, payload, "<html>"))
    r = client.registrar_evento(CHAVE, "<p/>")
    assert not r.ok and r.desfecho == desfecho and f"HTTP {status}" in r.erro_msg


def test_sem_retentativa(client, monkeypatch):
    chamadas = []

    def fake(*a, **k):
        chamadas.append(1)
        raise requests.exceptions.ReadTimeout("x")

    monkeypatch.setattr(client, "_req", fake)
    client.registrar_evento(CHAVE, "<p/>")
    assert len(chamadas) == 1


def test_prazo_do_evento_chega_a_requisicao(client, monkeypatch):
    visto = {}

    def fake(metodo, caminho, **kw):
        visto.update(kw)
        return FakeResp(201, {"eventoXmlGZipB64": _b64("<e/>")})

    monkeypatch.setattr(client, "_req", fake)
    client.registrar_evento(CHAVE, "<p/>", prazo_s=12.5)
    assert visto["prazo_s"] == 12.5


# ── o prazo total de relógio (gotejamento) ──────────────────────────────────
def test_prazo_total_corta_a_requisicao_lenta(pfx_teste, monkeypatch):
    caminho, senha = pfx_teste
    c = SefinClient(ambiente="homologacao", cert_pfx_path=str(caminho), senha=senha,
                    prazo_total_s=0.3)
    vistos = {}

    def lenta(metodo, url, **kw):
        vistos.update(kw)
        time.sleep(2)                      # resposta que goteja além do prazo
        return FakeResp(200, {})

    monkeypatch.setattr(c._sessao, "request", lenta)
    t0 = time.monotonic()
    with pytest.raises(sefin.PrazoEsgotado):
        c._req("GET", "x")
    assert time.monotonic() - t0 < 1.5
    assert vistos["timeout"] == 0.3        # cada operação também cabe no prazo


def test_prazo_total_estourado_no_evento_e_ambiguo(pfx_teste, monkeypatch):
    caminho, senha = pfx_teste
    c = SefinClient(ambiente="homologacao", cert_pfx_path=str(caminho), senha=senha)
    monkeypatch.setattr(c._sessao, "request", lambda *a, **k: time.sleep(2))
    r = c.registrar_evento(CHAVE, "<p/>", prazo_s=0.2)
    assert r.ambiguo


def test_sem_prazo_nao_ha_thread(client, monkeypatch):
    monkeypatch.setattr(sefin, "_com_prazo", _levanta(AssertionError("não devia")))
    monkeypatch.setattr(client._sessao, "request", lambda *a, **k: FakeResp(200, {}))
    assert client._req("GET", "x").status_code == 200


def test_timeout_em_par(pfx_teste):
    caminho, senha = pfx_teste
    c = SefinClient(ambiente="homologacao", cert_pfx_path=str(caminho), senha=senha,
                    timeout=(10, 80))
    assert c._timeout_ate(None) == (10, 80) and c._timeout_ate(30) == (10, 30)


def test_pkcs12_data_ou_arquivo(pfx_teste):
    caminho, senha = pfx_teste
    from pathlib import Path
    SefinClient(ambiente="homologacao", pkcs12_data=Path(caminho).read_bytes(), senha=senha)
    with pytest.raises(ValueError):
        SefinClient(ambiente="homologacao", senha=senha)
    with pytest.raises(ValueError):
        SefinClient(ambiente="homologacao", cert_pfx_path=str(caminho), senha=senha,
                    pkcs12_data=b"x")


# ── chave: o emitente ───────────────────────────────────────────────────────
CHAVE_CPF = "3304557" + "2" + "1" + "000" + "11144477735" + "0000000000147" + "2610" + "1" * 9 + "0"


def test_emitente_da_chave():
    assert chave.emitente_da_chave(CHAVE) == "11222333000181"
    assert chave.emitente_da_chave("NFS" + CHAVE) == "11222333000181"
    assert chave.emitente_da_chave(CHAVE_CPF) == "11144477735"
    assert chave.emitente_da_chave("123") is None
    assert chave.emitente_da_chave(CHAVE[:8] + "9" + CHAVE[9:]) is None    # tpInsc desconhecido
    alfa = CHAVE[:9] + "12ABC34501DE35" + CHAVE[23:]
    assert chave.emitente_da_chave(alfa) == "12ABC34501DE35"
    # CPF fora do layout esperado (sem os 3 zeros à esquerda): não sei → None, e nada se
    # recusa por isso (o lado seguro enquanto o layout do CPF não foi medido)
    cpf_estranho = CHAVE[:8] + "1" + "12311144477735" + CHAVE[23:]
    assert chave.emitente_da_chave(cpf_estranho) is None
    assert chave.chave_do_emitente(cpf_estranho, "11144477735") is None
    assert chave.chave_do_emitente(cpf_estranho, "12311144477735") is None


def test_chave_do_emitente():
    assert chave.chave_do_emitente(CHAVE, "11.222.333/0001-81") is True
    assert chave.chave_do_emitente(CHAVE, "99888777000166") is False
    assert chave.chave_do_emitente("123", "11222333000181") is None
    assert chave.chave_do_emitente(CHAVE, "") is None


def test_cancelamento_de_chave_de_outro_emitente_e_recusado_antes_de_assinar():
    with pytest.raises(ConfigError, match="outro emitente"):
        _pedido(autor="99.888.777/0001-66")
    # por procuração (autor ≠ emitente), quem chama desliga a conferência
    assert "<CNPJAutor>99888777000166</CNPJAutor>" in _pedido(
        autor="99.888.777/0001-66", conferir_emitente=False)


def test_validar_cancelamento_sem_autor_nao_confere_o_emitente():
    assert eventos.validar_cancelamento(CHAVE, 1, JUST, "direto") == []
    assert eventos.validar_cancelamento(CHAVE, 1, JUST, "direto", autor="99888777000166")


# ── autor alfanumérico e justificativa ───────────────────────────────────────
def test_autor_que_comeca_com_nfs_continua_cnpj():
    """`chave.limpar` tira o prefixo "NFS" da CHAVE; aplicado ao autor, um CNPJ alfanumérico
    que começasse com NFS virava CPFAutor de 11 posições."""
    autor = "NFS4ABCD00019"
    autor = autor + "5"                   # 14 posições, começa com NFS
    alfa = CHAVE[:9] + autor + CHAVE[23:]
    xml = _pedido(chave=alfa, autor=autor)
    assert f"<CNPJAutor>{autor}</CNPJAutor>" in xml and "CPFAutor" not in xml
    assert eventos.limpar_autor("nfs4.abcd/0001-95") == "NFS4ABCD000195"


def test_justificativa_ate_255_como_o_xsd():
    assert "<xMotivo>" + "x" * 255 + "</xMotivo>" in _pedido(justificativa="x" * 255)
    with pytest.raises(ConfigError, match="255"):
        _pedido(justificativa="x" * 256)
    assert eventos.JUSTIFICATIVA_MAX == 255


def test_assinatura_pelos_bytes_do_pkcs12(pfx_teste):
    from pathlib import Path

    from test_golden import _verifica_assinatura

    from pynfsenacional import assinatura
    caminho, senha = pfx_teste
    xml = assinatura.assinar_xml(_pedido(), "infPedReg", senha=senha,
                                 pkcs12_data=Path(caminho).read_bytes())
    assert _verifica_assinatura(xml)
    with pytest.raises(ValueError):
        assinatura.assinar_xml(_pedido(), "infPedReg", senha=senha)
