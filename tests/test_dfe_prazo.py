"""Caixa DF-e: o prazo total, a gravação por página, o XML que não é UTF-8, o nome do arquivo
do evento e a gravação atômica — e a conferência do servidor do ADN. Sem rede."""

from __future__ import annotations

import base64
import gzip
import threading
import warnings

import pytest
from test_eventos_dfe import FakeAdn, FakeResp, _item, _nfse

from pynfsenacional import dfe
from pynfsenacional.sefin import SefinClient


class Relogio:
    """Relógio falso: anda quando alguém "dorme" ou quando uma página é pedida."""

    def __init__(self, passo_por_pagina=0.0):
        self.t = 0.0
        self.passo = passo_por_pagina

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.t += s


class AdnLento(FakeAdn):
    def __init__(self, respostas, relogio, custo):
        super().__init__(respostas)
        self.relogio, self.custo = relogio, custo
        self.prazos = []

    def distribuicao_dfe(self, nsu, cnpj, lote=True, prazo_s=None):
        self.prazos.append(prazo_s)
        self.relogio.t += self.custo
        return super().distribuicao_dfe(nsu, cnpj, lote)


FIM = FakeResp(404, {"StatusProcessamento": "NenhumDocumentoLocalizado"})


def _pag(*nsus):
    return FakeResp(200, {"StatusProcessamento": "DocumentosLocalizados",
                          "LoteDFe": [_item(n) for n in nsus]})


# ── prazo total ──────────────────────────────────────────────────────────────
def test_prazo_devolve_o_parcial_com_o_nsu_consistente():
    rel = Relogio()
    adn = AdnLento([_pag(1, 2), _pag(3, 4), _pag(5, 6)], rel, custo=4.0)
    r = dfe.sincronizar(adn, "11222333000181", 0, prazo_s=10, dormir=rel.dormir,
                        relogio=rel, max_paginas=100)
    # 4 s por página + 1 s de pausa: a 3ª página não cabe no que resta
    assert r.prazo_esgotado and r.tem_mais and not r.parcial and r.erro is None
    assert r.ultimo_nsu == 4 and [d.nsu for d in r.documentos] == [1, 2, 3, 4]
    assert len(adn.pedidos) == 2


def test_prazo_corta_cada_requisicao_no_que_resta():
    rel = Relogio()
    adn = AdnLento([_pag(1), FakeResp(404, {"StatusProcessamento": "NenhumDocumentoLocalizado"})],
                   rel, custo=2.0)
    dfe.sincronizar(adn, "11222333000181", 0, prazo_s=30, dormir=rel.dormir, relogio=rel)
    assert adn.prazos == [30, 27]           # 30 − 2 (página) − 1 (pausa)


def test_prazo_nao_comeca_espera_de_429_que_nao_cabe():
    rel = Relogio()
    adn = AdnLento([FakeResp(429), FakeResp(429), _pag(1)], rel, custo=0.5)
    r = dfe.sincronizar(adn, "11222333000181", 7, prazo_s=5, dormir=rel.dormir, relogio=rel)
    # 1ª espera 3 s cabe (resta 4,5); a 2ª, de 6 s, não
    assert r.prazo_esgotado and r.ultimo_nsu == 7 and len(adn.pedidos) == 2


def test_requisicao_que_estoura_o_prazo_e_prazo_nao_erro():
    rel = Relogio()

    class Adn(AdnLento):
        def distribuicao_dfe(self, nsu, cnpj, lote=True, prazo_s=None):
            if self.pedidos:
                self.relogio.t += prazo_s
                raise TimeoutError("prazo")
            return super().distribuicao_dfe(nsu, cnpj, lote, prazo_s)

    adn = Adn([_pag(1)], rel, custo=1.0)
    r = dfe.sincronizar(adn, "11222333000181", 0, prazo_s=20, dormir=rel.dormir, relogio=rel)
    assert r.prazo_esgotado and not r.parcial and r.ultimo_nsu == 1


def test_sem_prazo_nao_passa_prazo_ao_cliente():
    adn = FakeAdn([_pag(1), FakeResp(404, {"StatusProcessamento": "NenhumDocumentoLocalizado"})])
    r = dfe.sincronizar(adn, "11222333000181", 0, dormir=lambda s: None)   # FakeAdn sem prazo_s
    assert r.ultimo_nsu == 1 and not r.prazo_esgotado


# ── gravação por página ──────────────────────────────────────────────────────
def test_callback_recebe_cada_pagina_antes_do_nsu():
    adn = FakeAdn([_pag(1, 2), _pag(3), FakeResp(404, {"StatusProcessamento":
                                                       "NenhumDocumentoLocalizado"})])
    vistos = []
    r = dfe.sincronizar(adn, "11222333000181", 0, dormir=lambda s: None,
                        ao_receber_pagina=lambda docs, ult: vistos.append(
                            ([d.nsu for d in docs], ult)))
    assert vistos == [([1, 2], 2), ([3], 3)] and r.ultimo_nsu == 3


def test_callback_que_falha_para_no_fim_da_pagina_anterior():
    adn = FakeAdn([_pag(1, 2), _pag(3, 4), _pag(5)])

    def gravar(docs, ult):
        if ult == 4:
            raise OSError(28, "No space left on device")

    r = dfe.sincronizar(adn, "11222333000181", 0, dormir=lambda s: None, ao_receber_pagina=gravar)
    assert r.parcial and "não foi gravada" in r.erro and "OSError" in r.erro
    assert r.ultimo_nsu == 2 and [d.nsu for d in r.documentos] == [1, 2]
    assert len(adn.pedidos) == 2


# ── XML que não é UTF-8, ilegível e os bytes ─────────────────────────────────
def _b64_bytes(b):
    return base64.b64encode(gzip.compress(b)).decode()


def test_xml_latin1_declarado_nao_some():
    """O PHP gravava os bytes crus; até a 1.6.0 o Python descartava o item calado e o NSU
    passava por cima. Agora o texto sai pela codificação declarada e os bytes ficam."""
    cru = ('<?xml version="1.0" encoding="ISO-8859-1"?>' + _nfse("11222333000181")
           .replace("<infNFSe>", "<infNFSe><xDesc>Serviço</xDesc>")).encode("latin-1")
    item = {**_item(10), "ArquivoXml": _b64_bytes(cru)}
    r = dfe.sincronizar(FakeAdn([FakeResp(200, {"LoteDFe": [item]}), FIM]),
                        "11222333000181", 0, dormir=lambda s: None)
    doc, = r.documentos
    assert doc.xml_bytes == cru and "Serviço" in doc.xml and not doc.ilegivel
    assert doc.classificar("11222333000181") == "emitida" and r.ilegiveis == []


def test_xml_ilegivel_aparece_na_lista():
    item = {**_item(11), "ArquivoXml": "isto-nao-e-base64-gzip"}
    sem_decl = {**_item(12), "ArquivoXml": _b64_bytes("<a>ç</a>".encode("latin-1"))}
    r = dfe.sincronizar(FakeAdn([FakeResp(200, {"LoteDFe": [item, sem_decl]}), FIM]),
                        "11222333000181", 0, dormir=lambda s: None)
    assert r.ilegiveis == [11, 12] and r.ultimo_nsu == 12
    a, b = r.documentos
    assert a.ilegivel and a.xml is None and a.xml_bytes is None
    assert b.ilegivel and b.xml is None and b.xml_bytes == "<a>ç</a>".encode("latin-1")


def test_decodificar_xml():
    assert dfe.decodificar_xml("<a>ç</a>".encode()) == "<a>ç</a>"
    assert dfe.decodificar_xml(b'<?xml version="1.0" encoding="windows-1252"?><a>\x80</a>'
                               ).endswith("<a>\u20ac</a>")
    assert dfe.decodificar_xml(b'<?xml version="1.0" encoding="nao-existe"?><a>\xff</a>') is None


# ── nome do arquivo e gravação atômica ───────────────────────────────────────
def _doc(nsu, tipo="NFSE", evento=None, chave="3" * 50, xml="<x/>"):
    return dfe.DocumentoDfe(nsu=nsu, tipo_documento=tipo, chave_acesso=chave,
                            tipo_evento=evento, data_hora=None, xml=xml,
                            xml_bytes=xml.encode() if xml else None)


def test_nome_do_evento_nao_colide_com_a_nota_nem_com_outro_evento():
    nota = _doc(1)
    ev1, ev2 = _doc(2, "EVENTO", "CANCELAMENTO"), _doc(3, "EVENTO", "CONFIRMACAO")
    nomes = [d.nome_arquivo() for d in (nota, ev1, ev2)]
    assert nomes == ["3" * 50 + ".xml", "3" * 50 + "_ev2.xml", "3" * 50 + "_ev3.xml"]
    assert _doc(9, chave=None).nome_arquivo() == "nsu9.xml"
    assert _doc(9, chave="../x/y").nome_arquivo() == "xy.xml"


def test_gravar_e_atomico_e_grava_os_bytes(tmp_path, monkeypatch):
    cru = '<?xml version="1.0" encoding="ISO-8859-1"?><a>ç</a>'.encode("latin-1")
    d = dfe.DocumentoDfe(nsu=5, tipo_documento="NFSE", chave_acesso="3" * 50, tipo_evento=None,
                         data_hora=None, xml="<a>ç</a>", xml_bytes=cru)
    caminho = d.gravar(tmp_path / "2026" / "10")
    assert caminho.read_bytes() == cru
    # um processo morto no meio da escrita não deixa o arquivo final pela metade
    import os

    def morre(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", morre)
    d2 = _doc(5, xml="<novo/>")
    with pytest.raises(KeyboardInterrupt):
        d2.gravar(tmp_path / "2026" / "10")
    assert caminho.read_bytes() == cru                        # o antigo segue inteiro
    assert [p.name for p in (tmp_path / "2026" / "10").iterdir()] == [caminho.name]


def test_gravar_sem_xml_nao_grava(tmp_path):
    assert _doc(1, xml=None).gravar(tmp_path) is None and list(tmp_path.iterdir()) == []


# ── ADN: sempre confere o servidor; o aviso de TLS não mexe nos filtros globais ─
def test_municipio_proprio_nao_desliga_a_conferencia_do_adn(pfx_teste, monkeypatch):
    caminho, senha = pfx_teste
    c = SefinClient(ambiente="producao", cert_pfx_path=str(caminho), senha=senha,
                    codigo_municipio="3511102")
    vistos = []
    monkeypatch.setattr(c._sessao, "request",
                        lambda m, url, **kw: vistos.append((url, kw["verify"])) or FakeResp(404))
    c.distribuicao_dfe(1, "11222333000181")
    c._req("HEAD", "dps/1")
    assert vistos[0] == ("https://adn.nfse.gov.br/contribuintes/DFe/1", True)
    assert vistos[1][1] is False and "164.152.60.237" in vistos[1][0]
    assert c.verificar_servidor is False and c.verificar_adn is True


def test_requisicoes_em_threads_nao_alteram_os_filtros_globais(pfx_teste, monkeypatch):
    caminho, senha = pfx_teste
    sem = SefinClient(ambiente="producao", cert_pfx_path=str(caminho), senha=senha,
                      codigo_municipio="3511102")
    com = SefinClient(ambiente="producao", cert_pfx_path=str(caminho), senha=senha)
    barreira = threading.Barrier(2)

    def lenta(*a, **k):
        barreira.wait(timeout=5)
        return FakeResp(200)

    for c in (sem, com):
        monkeypatch.setattr(c._sessao, "request", lenta)
    antes = list(warnings.filters)
    ts = [threading.Thread(target=c._req, args=("HEAD", "dps/1")) for c in (sem, com)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    assert list(warnings.filters) == antes


def test_requisicao_nao_salva_nem_restaura_filtros(pfx_teste, monkeypatch):
    """`catch_warnings` troca a lista GLOBAL de filtros (não é seguro entre threads): a
    requisição não pode usá-lo."""
    caminho, senha = pfx_teste
    c = SefinClient(ambiente="producao", cert_pfx_path=str(caminho), senha=senha,
                    codigo_municipio="3511102")
    monkeypatch.setattr(c._sessao, "request", lambda *a, **k: FakeResp(200))
    usos = []
    original = warnings.catch_warnings

    def espiao(*a, **k):
        usos.append(1)
        return original(*a, **k)

    with monkeypatch.context() as m:
        m.setattr(warnings, "catch_warnings", espiao)
        status = c._req("HEAD", "dps/1").status_code
    assert status == 200 and usos == []
