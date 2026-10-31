"""Cancelamento (eventos.py), distribuição DF-e (dfe.py), a chave de acesso (chave.py) e as
partes novas do transporte (sefin.py) — tudo sem rede."""

from __future__ import annotations

import base64
import gzip
from datetime import datetime

import pytest
from lxml import etree
from test_golden import _verifica_assinatura

from pynfsenacional import assinatura, chave, dfe, eventos, sefin
from pynfsenacional.config import ConfigError
from pynfsenacional.relogio import FUSO_BRASILIA
from pynfsenacional.sefin import SefinClient

CHAVE = "3304557" + "2" + "2" + "11222333000181" + "0000000000147" + "2610" + "123456789" + "0"
JUST = "Erro na emissão da nota fiscal"


class FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("sem JSON")
        return self._payload


def _b64(xml):
    return base64.b64encode(gzip.compress(xml.encode())).decode()


@pytest.fixture
def client(pfx_teste):
    caminho, senha = pfx_teste
    return SefinClient(ambiente="homologacao", cert_pfx_path=str(caminho), senha=senha)


# ── chave ────────────────────────────────────────────────────────────────────
def test_numero_da_chave():
    assert chave.numero_da_chave(CHAVE) == "147"
    assert chave.numero_da_chave("NFS" + CHAVE) == "147"
    assert chave.numero_da_chave("123") is None
    assert chave.numero_da_chave(None) is None
    alfa = CHAVE[:9] + "12ABC34501DE35" + CHAVE[23:]       # CNPJ alfanumérico
    assert chave.numero_da_chave(alfa) == "147"


def test_chave_do_xml():
    assert chave.chave_do_xml(f'<NFSe><infNFSe Id="NFS{CHAVE}" versao="1.01"/></NFSe>') == CHAVE
    assert chave.chave_do_xml("<NFSe/>") is None


# ── eventos: o pedido de cancelamento ────────────────────────────────────────
def _pedido(modo="direto", **kw):
    base = dict(chave=CHAVE, autor="11.222.333/0001-81", motivo=1, justificativa=JUST,
                ambiente="producao", modo=modo,
                dh_evento=datetime(2026, 10, 31, 10, 0, 0, tzinfo=FUSO_BRASILIA),
                ver_aplic="PyNFSeNacional-0.1")
    base.update(kw)
    return eventos.montar_cancelamento(**base)


def test_pedido_de_cancelamento_direto_byte_a_byte():
    """A mesma forma do pedido que a implementação de referência registra em produção."""
    assert _pedido() == (
        '<pedRegEvento xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">'
        f'<infPedReg Id="PRE{CHAVE}101101"><tpAmb>1</tpAmb><verAplic>PyNFSeNacional-0.1'
        "</verAplic><dhEvento>2026-10-31T10:00:00-03:00</dhEvento>"
        f"<CNPJAutor>11222333000181</CNPJAutor><chNFSe>{CHAVE}</chNFSe><e101101>"
        "<xDesc>Cancelamento de NFS-e</xDesc><cMotivo>1</cMotivo>"
        f"<xMotivo>{JUST}</xMotivo></e101101></infPedReg></pedRegEvento>"
    )


def test_pedido_de_analise_fiscal_tem_xdesc_acentuado():
    xml = _pedido(modo="analise", ambiente="homologacao")
    assert f'Id="PRE{CHAVE}101103"' in xml and "<tpAmb>2</tpAmb>" in xml
    # o XSD lista SEM acento, mas a SEFIN só aceita acentuado (sem acento: E1235)
    assert "<xDesc>Solicitação de Análise Fiscal para Cancelamento de NFS-e</xDesc>" in xml


def test_pedido_por_cpf():
    assert "<CPFAutor>11144477735</CPFAutor>" in _pedido(autor="111.444.777-35")


@pytest.mark.parametrize("kw", [
    {"justificativa": "curta demais"}, {"justificativa": "x" * 201}, {"motivo": 3},
    {"modo": "outro"}, {"chave": "123"}, {"ambiente": "teste"}, {"autor": "123"},
])
def test_pedido_invalido(kw):
    with pytest.raises(ConfigError):
        _pedido(**kw)


def test_pedido_assinado_verifica(pfx_teste):
    caminho, senha = pfx_teste
    assinado = assinatura.assinar_xml(_pedido(), "infPedReg", cert_pfx_path=str(caminho),
                                      senha=senha)
    raiz = etree.fromstring(assinado.encode())
    assert [c.tag.split("}")[1] for c in raiz] == ["infPedReg", "Signature"]
    assert f'URI="#PRE{CHAVE}101101"' in assinado
    assert assinado.startswith("<?xml version='1.0' encoding='UTF-8'?>")
    assert _verifica_assinatura(assinado)


# ── sefin: todos os erros, HTTP explicado, consulta, evento, conferência TLS ─
def test_todos_os_erros_chegam(client, monkeypatch):
    payload = {"erros": [{"codigo": "E0312", "descricao": "não administrado"},
                         {"Codigo": "E0712", "Descricao": "indTotTrib", "Complemento": "ME"}]}
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(400, payload))
    r = client.emitir("<DPS/>")
    assert r.erro_codigo == "E0312" and len(r.erros) == 2
    assert r.erro_msg == "não administrado | [E0712] indTotTrib — ME"


def test_erro_como_objeto_unico(client, monkeypatch):
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(
        400, {"erro": {"codigo": "E0008", "descricao": "data"}}))
    assert client.emitir("<DPS/>").erro_codigo == "E0008"


@pytest.mark.parametrize("status, trecho", [(503, "fora do ar"), (403, "certificado"),
                                            (429, "requisições demais"), (418, None)])
def test_falha_http_explicada(client, monkeypatch, status, trecho):
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(status, None, "<html>"))
    r = client.emitir("<DPS/>")
    assert not r.ok and r.http_status == status
    assert f"HTTP {status}" in r.erro_msg                 # quem consome casa o status por aqui
    assert (trecho in r.erro_msg) if trecho else (" — " not in r.erro_msg)


def test_consultar_nfse(client, monkeypatch):
    chamadas = []

    def fake(metodo, caminho, **kw):
        chamadas.append((metodo, caminho))
        if caminho.endswith("404"):
            return FakeResp(404)
        if caminho.endswith("503"):
            return FakeResp(503)
        return FakeResp(200, {"nfseXmlGZipB64": _b64("<NFSe>ok</NFSe>")})

    monkeypatch.setattr(client, "_req", fake)
    assert client.consultar_nfse("33OK") == "<NFSe>ok</NFSe>"
    assert chamadas[0] == ("GET", "nfse/33OK")
    assert client.consultar_nfse("x404") is None
    with pytest.raises(RuntimeError, match="HTTP 503"):     # "não sei" nunca vira "não existe"
        client.consultar_nfse("x503")


def test_registrar_evento(client, monkeypatch):
    capturado = {}

    def fake(metodo, caminho, **kw):
        capturado.update(metodo=metodo, caminho=caminho, json=kw["json"])
        return FakeResp(201, {"eventoXmlGZipB64": _b64("<evento/>")})

    monkeypatch.setattr(client, "_req", fake)
    r = client.registrar_evento(CHAVE, "<pedRegEvento/>")
    assert r.ok and r.evento_xml == "<evento/>"
    assert capturado["metodo"] == "POST" and capturado["caminho"] == f"nfse/{CHAVE}/eventos"
    b64 = capturado["json"]["pedidoRegistroEventoXmlGZipB64"]
    assert gzip.decompress(base64.b64decode(b64)).decode() == "<pedRegEvento/>"


def test_registrar_evento_recusado(client, monkeypatch):
    monkeypatch.setattr(client, "_req", lambda *a, **k: FakeResp(
        400, {"erro": [{"codigo": "E0823", "descricao": "acima do permitido"}]}))
    r = client.registrar_evento(CHAVE, "<pedRegEvento/>")
    assert not r.ok and r.erro_codigo == "E0823" and r.erro_msg == "acima do permitido"


def test_conferencia_do_servidor(pfx_teste):
    caminho, senha = pfx_teste

    def c(**kw):
        return SefinClient(ambiente="producao", cert_pfx_path=str(caminho), senha=senha, **kw)

    assert c().verificar_servidor is True                         # endpoint nacional
    assert c(codigo_municipio="3511102").verificar_servidor is False   # IP cru de município
    assert c(verificar_servidor="/etc/ca.pem").verificar_servidor == "/etc/ca.pem"
    assert c(verificar_servidor=False).verificar_servidor is False


# ── dfe: paginação, 429, fim, classificação ─────────────────────────────────
def _nfse(prest):
    return (f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe><emit><CNPJ>{prest}'
            f"</CNPJ></emit><DPS><infDPS><prest><CNPJ>{prest}</CNPJ></prest></infDPS></DPS>"
            "</infNFSe></NFSe>")


def _item(nsu, prest="11222333000181", tipo="NFSE", evento=None):
    return {"NSU": nsu, "TipoDocumento": tipo, "ChaveAcesso": f"{nsu:050d}",
            "TipoEvento": evento, "DataHoraGeracao": "2026-10-01T10:00:00",
            "ArquivoXml": _b64(_nfse(prest))}


class FakeAdn:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []

    def distribuicao_dfe(self, nsu, cnpj, lote=True):
        self.pedidos.append((nsu, cnpj))
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_dfe_pagina_ate_o_fim_e_classifica():
    adn = FakeAdn([
        FakeResp(200, {"StatusProcessamento": "DocumentosLocalizados",
                       "LoteDFe": [_item(5), _item(6, prest="99888777000166")]}),
        FakeResp(200, {"StatusProcessamento": "DocumentosLocalizados",
                       "LoteDFe": [_item(7, tipo="EVENTO", evento="CANCELAMENTO")]}),
        FakeResp(404, {"StatusProcessamento": "NenhumDocumentoLocalizado", "LoteDFe": []}),
    ])
    pausas = []
    r = dfe.sincronizar(adn, "11.222.333/0001-81", 4, dormir=pausas.append)
    assert [p[0] for p in adn.pedidos] == [4, 6, 7]       # cada página parte do último NSU
    assert adn.pedidos[0][1] == "11222333000181"
    assert r.ultimo_nsu == 7 and not r.tem_mais and not r.parcial
    assert [d.classificar("11222333000181") for d in r.documentos] == [
        "emitida", "recebida", "evento"]
    assert pausas == [1.0, 1.0]


def test_dfe_status_em_caixa_alta_encerra():
    """Medido em homologação (31/10/2026): o ADN escreve NENHUM_DOCUMENTO_LOCALIZADO."""
    adn = FakeAdn([FakeResp(200, {"StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO",
                                  "LoteDFe": [_item(1)]})])
    r = dfe.sincronizar(adn, "11222333000181", 0, dormir=lambda s: None)
    assert len(adn.pedidos) == 1 and r.ultimo_nsu == 1 and not r.tem_mais


def test_dfe_429_repete_a_mesma_pagina():
    adn = FakeAdn([FakeResp(429), FakeResp(429),
                   FakeResp(200, {"StatusProcessamento": "NenhumDocumentoLocalizado",
                                  "LoteDFe": [_item(3)]})])
    pausas = []
    r = dfe.sincronizar(adn, "11222333000181", 2, dormir=pausas.append)
    assert [p[0] for p in adn.pedidos] == [2, 2, 2] and pausas == [3.0, 6.0]
    assert r.ultimo_nsu == 3 and not r.parcial


def test_dfe_para_no_teto_de_paginas():
    adn = FakeAdn([FakeResp(200, {"LoteDFe": [_item(n)]}) for n in (1, 2)])
    r = dfe.sincronizar(adn, "11222333000181", 0, max_paginas=2, dormir=lambda s: None)
    assert r.tem_mais and r.ultimo_nsu == 2 and len(r.documentos) == 2


@pytest.mark.parametrize("falha, trecho", [(FakeResp(503), "HTTP 503"),
                                           (ConnectionError("caiu"), "ConnectionError")])
def test_dfe_falha_devolve_o_parcial(falha, trecho):
    adn = FakeAdn([FakeResp(200, {"LoteDFe": [_item(9)]}), falha])
    r = dfe.sincronizar(adn, "11222333000181", 8, dormir=lambda s: None)
    assert r.parcial and trecho in r.erro
    assert r.ultimo_nsu == 9 and len(r.documentos) == 1   # o que veio fica


def test_dfe_nsu_negativo():
    with pytest.raises(ValueError):
        dfe.sincronizar(FakeAdn([]), "11222333000181", -1)


def test_distribuicao_dfe_monta_a_url(client, monkeypatch):
    capturado = {}

    def fake(metodo, url, **kw):
        capturado.update(metodo=metodo, url=url, params=kw["params"])
        return FakeResp(404)

    monkeypatch.setattr(client, "_req_url", fake)
    client.distribuicao_dfe(12, "11222333000181")
    assert capturado["url"] == ("https://adn.producaorestrita.nfse.gov.br"
                                "/contribuintes/DFe/12")
    assert capturado["params"] == {"cnpjConsulta": "11222333000181", "lote": "true"}
    assert sefin.ENDPOINTS_ADN["producao"] == "https://adn.nfse.gov.br"
