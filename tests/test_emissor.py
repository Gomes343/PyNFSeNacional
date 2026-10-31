"""Fase 5: orquestração do Emissor.emitir() ponta-a-ponta, com o SEFIN MOCKADO.

Exercita o pipeline real (validar → montar DPS → assinar com cert de teste) e o
roteamento do resultado (sucesso/idempotência/erro) + o contador de nDPS, sem rede.
Também consultar/cancelar/sincronizar_dfe, com o mesmo transporte falso.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from lxml import etree

from pynfsenacional import ClienteConfig, ConfigError, Emissor
from pynfsenacional.emissor import mesma_nota
from pynfsenacional.sefin import RespostaEvento, RespostaSefin

CPF_TOMADOR = "11144477735"
TOMADOR = {"cpf_cnpj": CPF_TOMADOR, "nome": "Fulano de Tal"}
# chave fictícia: cMun 3304557 · amb 2 · tpInsc 2 · CNPJ de teste · nNFSe 147 · resto qualquer
CHAVE = "3304557" + "2" + "2" + "11222333000181" + "0000000000147" + "2610" + "123456789" + "0"


def nfse_xml(*, valor="150.00", doc=CPF_TOMADOR, numero="147", chave=CHAVE):
    """XML mínimo de NFS-e — só o que a lib lê (Id, nNFSe, vServ, toma)."""
    toma = f"<toma><CPF>{doc}</CPF></toma>" if doc else ""
    return (f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS{chave}">'
            f"<nNFSe>{numero}</nNFSe><DPS><infDPS><prest><CNPJ>11222333000181</CNPJ></prest>"
            f"{toma}<valores><vServPrest><vServ>{valor}</vServ></vServPrest></valores>"
            f"</infDPS></DPS></infNFSe></NFSe>")


class FakeSefin:
    """`existentes`: nDPS (int) → (chave, xml|None) das DPS que já viraram nota."""

    def __init__(self, *, existentes=None, resp=None, evento=None, falha_xml=False):
        self.existentes = existentes or {}
        self.resp = resp
        self.evento = evento
        self.falha_xml = falha_xml
        self.emitiu = None              # nDPS da DPS enviada
        self.evento_enviado = None
        self.verificados = []

    def verificar_dps(self, idd):
        n = int(idd[-15:])
        self.verificados.append(n)
        return n in self.existentes

    def consultar_dps(self, idd):
        return self.existentes[int(idd[-15:])][0]

    def consultar_nfse(self, chave):
        if self.falha_xml:
            raise RuntimeError("consulta da NFS-e falhou (HTTP 503)")
        for ch, xml in self.existentes.values():
            if ch == chave:
                return xml
        return None

    def emitir(self, xml):
        assert "<Signature" in xml          # chegou ASSINADO ao transporte
        raiz = etree.fromstring(xml.encode())
        self.emitiu = int(raiz.find(".//{*}nDPS").text)
        return self.resp

    def registrar_evento(self, chave, xml):
        self.evento_enviado = (chave, xml)
        return self.evento


@pytest.fixture
def emissor(config_dict, pfx_teste, tmp_path):
    caminho, senha = pfx_teste
    config_dict["certificado"] = {"path": str(caminho), "senha": senha}
    return Emissor(ClienteConfig.from_dict(config_dict), out_dir=tmp_path)


def _contador(emissor):
    arq = emissor.out_dir / f"numero_{emissor.cfg.id}_homologacao.txt"
    return arq.read_text() if arq.exists() else None


def _emitir(emissor, monkeypatch, fake, valor=Decimal("150.00"), **kw):
    monkeypatch.setattr(emissor, "_sefin_client", lambda: fake)
    return emissor.emitir(valor=valor, descricao="Servico de teste", tomador=TOMADOR, **kw)


def _ok(chave="33OK", numero="147"):
    return RespostaSefin(ok=True, chave_acesso=chave, numero_nfse=numero, nfse_xml="<NFSe/>")


def test_emitir_sucesso_e_incrementa_contador(emissor, monkeypatch):
    fake = FakeSefin(resp=_ok())
    nota = _emitir(emissor, monkeypatch, fake)
    assert nota.emitida and nota.status == "ok"
    assert nota.chave_acesso == "33OK" and nota.numero_nfse == "147"
    assert nota.id_dps.startswith("DPS") and len(nota.id_dps) == 45
    assert fake.emitiu == 1
    # contador: semente "1" → próximo "2" gravado SÓ após sucesso
    assert _contador(emissor) == "2"


def test_emitir_sucesso_sem_nnfse_tira_o_numero_da_chave(emissor, monkeypatch):
    fake = FakeSefin(resp=RespostaSefin(ok=True, chave_acesso=CHAVE, nfse_xml="<NFSe/>"))
    assert _emitir(emissor, monkeypatch, fake).numero_nfse == "147"


def test_emitir_aceita_float_str_e_decimal(emissor, monkeypatch):
    for valor in (150.0, "150,00", "150.00", 150, Decimal("150")):
        fake = FakeSefin(resp=_ok())
        assert _emitir(emissor, monkeypatch, fake, valor=valor).emitida


@pytest.mark.parametrize("valor", [0, "0,00", -5, "abc"])
def test_emitir_valor_invalido_para_antes_da_rede(emissor, monkeypatch, valor):
    fake = FakeSefin(resp=_ok())
    with pytest.raises(ConfigError):
        _emitir(emissor, monkeypatch, fake, valor=valor)
    assert fake.verificados == [] and fake.emitiu is None


def test_ja_emitida_mesma_nota_recupera_xml_e_avanca_contador(emissor, monkeypatch):
    fake = FakeSefin(existentes={1: (CHAVE, nfse_xml())})
    nota = _emitir(emissor, monkeypatch, fake)
    assert nota.status == "ja_emitida" and nota.emitida
    assert nota.chave_acesso == CHAVE and nota.numero_nfse == "147"
    assert nota.nfse_xml and "<vServ>150.00</vServ>" in nota.nfse_xml   # dá para gerar o DANFSe
    assert fake.emitiu is None                 # NÃO reemitiu
    assert _contador(emissor) == "2"


def test_ja_emitida_nao_trava_o_contador(emissor, monkeypatch):
    """O defeito da 1.1.0: resposta perdida → toda emissão seguinte voltava 'já emitida'."""
    fake = FakeSefin(existentes={1: (CHAVE, nfse_xml())}, resp=_ok("33NOVA"))
    assert _emitir(emissor, monkeypatch, fake).status == "ja_emitida"
    nova = _emitir(emissor, monkeypatch, fake, valor=Decimal("99.90"))
    assert nova.status == "ok" and nova.chave_acesso == "33NOVA"
    assert fake.emitiu == 2 and _contador(emissor) == "3"


def test_ja_emitida_sem_xml_conta_como_feita(emissor, monkeypatch):
    """Sem o XML não dá para conferir se é a mesma nota: o ambíguo conta como feito."""
    fake = FakeSefin(existentes={1: (CHAVE, None)}, falha_xml=True)
    nota = _emitir(emissor, monkeypatch, fake)
    assert nota.status == "ja_emitida" and nota.emitida and nota.nfse_xml is None
    assert nota.numero_nfse == "147"           # da chave
    assert fake.emitiu is None and _contador(emissor) == "2"


def test_contador_atrasado_pula_numero_de_outra_nota(emissor, monkeypatch):
    outra = nfse_xml(valor="80.00", chave=CHAVE[:-1] + "1")
    fake = FakeSefin(existentes={1: (CHAVE[:-1] + "1", outra)}, resp=_ok())
    nota = _emitir(emissor, monkeypatch, fake)
    assert nota.status == "ok" and fake.emitiu == 2      # pulou o nDPS 1, que é de outra nota
    assert _contador(emissor) == "3"


def test_contador_muito_atrasado_para_com_mensagem(emissor, monkeypatch):
    outras = {n: (f"{n:050d}", nfse_xml(valor="1.00")) for n in range(1, 30)}
    fake = FakeSefin(existentes=outras, resp=_ok())
    with pytest.raises(ConfigError, match="contador"):
        _emitir(emissor, monkeypatch, fake)
    assert fake.emitiu is None


def test_numero_explicito_nao_mexe_no_contador(emissor, monkeypatch):
    """Quem passa o nDPS controla a numeração — a lib só recupera a nota."""
    fake = FakeSefin(existentes={7: (CHAVE, nfse_xml(valor="80.00"))})
    nota = _emitir(emissor, monkeypatch, fake, numero="7")
    assert nota.status == "ja_emitida" and nota.chave_acesso == CHAVE and nota.nfse_xml
    assert fake.emitiu is None and _contador(emissor) is None


def test_emitir_erro_nao_incrementa(emissor, monkeypatch):
    erros = [{"codigo": "E0312", "descricao": "não administrado", "complemento": None},
             {"codigo": "E0712", "descricao": "indTotTrib", "complemento": None}]
    fake = FakeSefin(resp=RespostaSefin(ok=False, erro_codigo="E0312", erros=erros,
                                        erro_msg="não administrado | [E0712] indTotTrib"))
    nota = _emitir(emissor, monkeypatch, fake)
    assert nota.status == "erro" and not nota.emitida
    assert nota.erro_msg.startswith("[E0312]") and "[E0712]" in nota.erro_msg
    assert [e["codigo"] for e in nota.erros] == ["E0312", "E0712"]
    assert _contador(emissor) is None


# ── mesma_nota ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("xml, valor, tomador, esperado", [
    (nfse_xml(), Decimal("150"), TOMADOR, True),
    (nfse_xml(), 150.0, {"cpf_cnpj": "111.444.777-35"}, True),
    (nfse_xml(valor="150.01"), Decimal("150"), TOMADOR, False),
    (nfse_xml(doc="52998224725"), Decimal("150"), TOMADOR, False),
    (nfse_xml(doc=None), Decimal("150"), None, True),          # consumidor final
    (nfse_xml(doc=None), Decimal("150"), TOMADOR, False),
    (None, Decimal("150"), TOMADOR, None),
    ("<quebrado", Decimal("150"), TOMADOR, None),
])
def test_mesma_nota(xml, valor, tomador, esperado):
    assert mesma_nota(xml, valor, tomador) is esperado


# ── consultar ────────────────────────────────────────────────────────────────
def test_consultar(emissor, monkeypatch):
    fake = FakeSefin(existentes={1: (CHAVE, nfse_xml())})
    monkeypatch.setattr(emissor, "_sefin_client", lambda: fake)
    nota = emissor.consultar("NFS" + CHAVE)
    assert nota.chave_acesso == CHAVE and nota.numero_nfse == "147" and nota.nfse_xml
    assert emissor.consultar("9" * 50) is None


# ── cancelar ─────────────────────────────────────────────────────────────────
JUST = "Erro na emissão da nota fiscal"


@pytest.mark.parametrize("modo, tipo, cancelada", [("direto", "101101", True),
                                                    ("analise", "101103", False)])
def test_cancelar(emissor, monkeypatch, modo, tipo, cancelada):
    fake = FakeSefin(evento=RespostaEvento(ok=True, evento_xml="<evento/>"))
    monkeypatch.setattr(emissor, "_sefin_client", lambda: fake)
    r = emissor.cancelar("NFS" + CHAVE, justificativa=JUST, modo=modo)
    assert r.ok and r.cancelada is cancelada and r.chave_acesso == CHAVE
    chave, xml = fake.evento_enviado
    assert chave == CHAVE
    raiz = etree.fromstring(xml.encode())
    inf = raiz.find("{*}infPedReg")
    assert inf.get("Id") == f"PRE{CHAVE}{tipo}"
    assert inf.find("{*}CNPJAutor").text == "11222333000181"
    assert inf.find("{*}tpAmb").text == "2"
    assert raiz[-1].tag.endswith("Signature")      # assinado, depois do infPedReg


def test_cancelar_recusado(emissor, monkeypatch):
    fake = FakeSefin(evento=RespostaEvento(ok=False, erro_codigo="E0823", erro_msg="acima"))
    monkeypatch.setattr(emissor, "_sefin_client", lambda: fake)
    r = emissor.cancelar(CHAVE, justificativa=JUST)
    assert not r.ok and not r.cancelada and r.erro_msg == "[E0823] acima"


@pytest.mark.parametrize("kw", [{"justificativa": "curta"}, {"justificativa": JUST, "motivo": 3},
                                {"justificativa": JUST, "modo": "xpto"}])
def test_cancelar_pedido_invalido_nao_toca_a_rede(emissor, monkeypatch, kw):
    fake = FakeSefin()
    monkeypatch.setattr(emissor, "_sefin_client", lambda: fake)
    with pytest.raises(ConfigError):
        emissor.cancelar(CHAVE, **kw)
    assert fake.evento_enviado is None
