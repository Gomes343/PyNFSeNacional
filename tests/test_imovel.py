"""O grupo IBSCBS/imovel (§23): locação de imóvel com o redutor social e os ajustes da base.

A prova de forma é o XSD oficial de cada leiaute (`tests/xsd/`); a de regra, os E-codes do Anexo I
da produção restrita (20/10/2026) que a lib confere antes de assinar.
"""

from __future__ import annotations

import copy
import logging
from decimal import Decimal
from typing import Any

import pytest
from conftest import CONFIG_VALIDA
from lxml import etree
from test_leiaute import _erros

from pynfsenacional import dps
from pynfsenacional import imovel as im
from pynfsenacional.config import LEIAUTE_NT009, LEIAUTE_PRODUCAO, ClienteConfig

NS = "{http://www.sped.fazenda.gov.br/nfse}"

# Locação residencial de uma PJ do Lucro Presumido: 99.03.01, NBS 1.1002.10.00, sem ISS
# (tribISSQN 4) e a classificação da tabela da calculadora: cIndOp 020201, CST 200, 200027 (−70%).
LOCACAO: dict[str, Any] = {
    **copy.deepcopy(CONFIG_VALIDA),
    "prestador": {"cnpj": "11222333000181", "codigo_municipio": "3555406",
                  "regime": {"opSimpNac": 1, "regEspTrib": 0}},
    "servico": {
        "codigo_municipio_prestacao": "3555406",
        "cTribNac": "990301",
        "cNBS": "110021000",
        "tributos": {"tribISSQN": 4, "piscofins_cst": "01", "tpRetPisCofins": "0",
                     "pTotTrib": {"pTotTribFed": "3.65", "pTotTribEst": "0", "pTotTribMun": "0"}},
        "ibscbs": {"cIndOp": "020201", "CST": "200", "cClassTrib": "200027", "indFinal": "0"},
    },
}
TOMADOR = {"cpf_cnpj": "11144477735", "nome": "INQUILINO EXEMPLO"}
UNIDADE_END = {"inscricao": "12.345.678", "endereco": {
    "cep": "11680000", "logradouro": "RUA DAS FLORES", "numero": "10",
    "complemento": "APTO 6", "bairro": "CENTRO"}}
APTO = {"codigo_municipio": "3555406",
        "locacao": {"copropriedade": 100, "vencimento_original": "2027-01-10"},
        "unidades": [{**UNIDADE_END, "ajustes": [
            {"tipo": "04", "valor": "600.00"},           # redutor social
            {"tipo": "01", "valor": "120.00"},           # IPTU cobrado e repassado
        ]}]}


def _cfg(**servico: Any) -> ClienteConfig:
    d = copy.deepcopy(LOCACAO)
    d["servico"].update(servico)
    return ClienteConfig.from_dict(d)


def _dps(imovel: dict[str, Any] | None, leiaute: str, valor: str = "1500.00",
         cfg: ClienteConfig | None = None) -> str:
    return dps.montar_dps(cfg or _cfg(), numero="1", valor=valor, descricao="Aluguel jan/2027",
                          tomador=TOMADOR, ambiente="producao", leiaute=leiaute,
                          dh_emi="2027-01-05T10:00:00-03:00", d_comp="2027-01-05",
                          imovel=imovel)


def _validar(imovel: dict[str, Any] | None, valor: str = "1500.00", nt009: bool = True,
             cfg: ClienteConfig | None = None) -> list[str]:
    return im.validar_imovel(imovel, (cfg or _cfg()).servico, valor, nt009=nt009)


def _filhos(el: etree._Element) -> list[str]:
    return [etree.QName(c).localname for c in el]


# ── A forma: o XSD de cada leiaute ───────────────────────────────────────────────────────────

def test_locacao_residencial_com_redutor_passa_no_xsd_da_nt009():
    xml = _dps(APTO, LEIAUTE_NT009)
    assert _erros(xml, LEIAUTE_NT009) == []
    g = etree.fromstring(xml.encode()).find(f".//{NS}IBSCBS")
    assert _filhos(g) == ["indFinal", "cIndOp", "indDest", "imovel", "valores"]
    i = g.find(f"{NS}imovel")
    assert _filhos(i) == ["cMun", "gLocacao", "gUnidImob"]
    assert _filhos(i.find(f"{NS}gLocacao")) == ["pCopropriedade", "vTotOper", "dVencOrig"]
    assert i.findtext(f"{NS}gLocacao/{NS}pCopropriedade") == "100.00"
    assert i.findtext(f"{NS}gLocacao/{NS}vTotOper") == "1500.00"
    u = i.find(f"{NS}gUnidImob")
    assert _filhos(u) == ["inscImobFisc", "end", "gAjusteBCLocImoveis", "gAjusteBCLocImoveis"]
    assert [(a.findtext(f"{NS}tpAjusteBCLocImoveis"), a.findtext(f"{NS}vAjusteBCLocImoveis"))
            for a in u.findall(f"{NS}gAjusteBCLocImoveis")] == [("04", "600.00"),
                                                                ("01", "120.00")]
    assert g.findtext(f"{NS}valores/{NS}trib/{NS}cClassTrib") == "200027"


def test_unidade_pelo_cib_e_varias_unidades():
    imovel = {"codigo_municipio": "3555406", "locacao": {},
              "unidades": [{"cib": "abc1234x", "ajustes": [{"tipo": "04", "valor": 600}]},
                           {"cib": "ZZZ00001", "ajustes": [{"tipo": "04", "valor": 600}]}]}
    xml = _dps(imovel, LEIAUTE_NT009, valor="2400.00")
    assert _erros(xml, LEIAUTE_NT009) == []
    us = etree.fromstring(xml.encode()).findall(f".//{NS}gUnidImob")
    assert [u.findtext(f"{NS}cCIB") for u in us] == ["ABC1234X", "ZZZ00001"]
    assert _validar(imovel, valor="2400.00") == []


def test_ajuste_99_leva_a_descricao():
    imovel = copy.deepcopy(APTO)
    imovel["unidades"][0]["ajustes"] = [{"tipo": "99", "descricao": "Seguro incendio",
                                         "valor": "35.50"}]
    xml = _dps(imovel, LEIAUTE_NT009)
    assert _erros(xml, LEIAUTE_NT009) == []
    aj = etree.fromstring(xml.encode()).find(f".//{NS}gAjusteBCLocImoveis")
    assert _filhos(aj) == ["tpAjusteBCLocImoveis", "xTpAjusteBCLocImoveis",
                           "vAjusteBCLocImoveis"]


def test_no_leiaute_de_producao_so_a_unidade_e_o_resto_vai_ao_log(caplog):
    caplog.set_level(logging.WARNING)
    xml = _dps(APTO, LEIAUTE_PRODUCAO)
    assert _erros(xml, LEIAUTE_PRODUCAO) == []
    i = etree.fromstring(xml.encode()).find(f".//{NS}IBSCBS/{NS}imovel")
    assert _filhos(i) == ["inscImobFisc", "end"]
    assert "locacao" in caplog.text and "ajustes da base" in caplog.text


def test_no_leiaute_de_producao_pelo_cib():
    imovel = {"codigo_municipio": "3555406", "unidades": [{"cib": "ABC1234X"}]}
    xml = _dps(imovel, LEIAUTE_PRODUCAO)
    assert _erros(xml, LEIAUTE_PRODUCAO) == []
    assert etree.fromstring(xml.encode()).findtext(f".//{NS}imovel/{NS}cCIB") == "ABC1234X"


def test_sem_imovel_a_dps_nao_muda():
    """Aditivo: quem não passa `imovel` recebe a DPS de sempre (os hashes pinados das outras
    suítes cobrem o resto)."""
    assert "imovel" not in _dps(None, LEIAUTE_NT009)


# ── As regras: E-codes do Anexo I conferidos antes de assinar ────────────────────────────────

def test_a_locacao_completa_nao_tem_problema():
    assert _validar(APTO) == []


def test_redutor_social_so_no_residencial_E0944():
    probs = _validar(APTO, cfg=_cfg(cNBS="110022000"))
    assert any(p.startswith("E0944") for p in probs)


def test_valor_da_nota_e_copropriedade_vezes_total_E0433():
    total = copy.deepcopy(APTO)
    total["locacao"]["valor_total"] = "1500.00"
    assert any(p.startswith("E0433") for p in _validar(total, valor="1400.00"))
    assert _validar(total, valor="1500.00") == []
    meio = copy.deepcopy(APTO)
    meio["locacao"] = {"copropriedade": "50", "valor_total": "1500.00"}
    assert _validar(meio, valor="750.00") == []
    assert any("valor_total é obrigatório" in p
               for p in _validar({**meio, "locacao": {"copropriedade": 50}}, valor="750.00"))


def test_descricao_so_no_tipo_99_E0949_E0954():
    sem = copy.deepcopy(APTO)
    sem["unidades"][0]["ajustes"] = [{"tipo": "99", "valor": "10"}]
    assert any(p.startswith("E0949") for p in _validar(sem))
    com = copy.deepcopy(APTO)
    com["unidades"][0]["ajustes"] = [{"tipo": "04", "valor": "600", "descricao": "x"}]
    assert any(p.startswith("E0954") for p in _validar(com))


def test_ajuste_maior_que_a_operacao_E0966_e_soma_maior_que_a_nota_E1547():
    grande = copy.deepcopy(APTO)
    grande["unidades"][0]["ajustes"] = [{"tipo": "01", "valor": "1600"}]
    probs = _validar(grande)
    assert any(p.startswith("E0966") for p in probs)
    assert any(p.startswith("E1547") for p in probs)


def test_locacao_exige_o_grupo_na_nt009_mas_nao_no_de_producao_E0937():
    assert any(p.startswith("E0937") for p in _validar(None))
    assert _validar(None, nt009=False) == []
    sem_loc = {k: v for k, v in APTO.items() if k != "locacao"}
    assert any(p.startswith("E0937") for p in _validar(sem_loc))


def test_operacao_com_imovel_exige_o_grupo_E0932_e_a_unidade_E0938():
    manut = _cfg(cTribNac="071001", cNBS="124069000",
                 ibscbs={"cIndOp": "020201", "CST": "000", "cClassTrib": "000001"})
    assert any(p.startswith("E0932") for p in _validar(None, cfg=manut))
    sem_unid = {"codigo_municipio": "3555406"}
    assert any(p.startswith("E0938") for p in _validar(sem_unid, cfg=manut))
    # obra (07.02.02) se identifica em serv/obra: fora da regra
    obra = _cfg(cTribNac="070202", cNBS="101053000",
                ibscbs={"cIndOp": "020201", "CST": "000", "cClassTrib": "000001"})
    assert _validar(None, cfg=obra) == []


def test_imovel_fora_de_operacao_com_imovel_E0928_e_locacao_fora_da_9903_E0936():
    consultoria = _cfg(cTribNac="170101", cNBS="113011000",
                       ibscbs={"cIndOp": "030101", "CST": "000", "cClassTrib": "000001"})
    probs = _validar(APTO, cfg=consultoria)
    assert any(p.startswith("E0928") for p in probs)
    assert any(p.startswith("E0936") for p in probs)
    assert any(p.startswith("E0939") for p in probs)


def test_locacao_com_cindop_que_nao_e_02_E0902():
    probs = _validar(APTO, cfg=_cfg(ibscbs={"cIndOp": "030101", "CST": "200",
                                            "cClassTrib": "200027"}))
    assert any(p.startswith("E0902") for p in probs)


@pytest.mark.parametrize("unidade,trecho", [
    ({"cib": "123"}, "E0933"),
    ({"endereco": {"cep": "11680000", "logradouro": "RUA"}}, "faltam ['numero']"),
    ({}, "cib OU pelo endereco"),
    ({"cib": "ABC1234X", "ajustes": [{"tipo": "05", "valor": 1}]}, ".tipo deve ser um de"),
    ({"cib": "ABC1234X", "ajustes": [{"tipo": "04", "valor": 0}]}, "maior que zero"),
])
def test_forma_da_unidade(unidade, trecho):
    imovel = {"codigo_municipio": "3555406", "locacao": {}, "unidades": [unidade]}
    assert any(trecho in p for p in _validar(imovel)), _validar(imovel)


def test_municipio_e_copropriedade_E0929_E0940():
    probs = _validar({**APTO, "codigo_municipio": "355", "locacao": {"copropriedade": 120}})
    assert any(p.startswith("E0929") for p in probs)
    assert any(p.startswith("E0940") for p in probs)


def test_imovel_sem_grupo_ibscbs_e_recusado():
    cfg = _cfg(ibscbs={})
    assert any("só vai dentro do grupo IBS/CBS" in p for p in _validar(APTO, cfg=cfg))


def test_e_locacao():
    assert im.e_locacao("990301") and im.e_locacao("99.03.05")
    assert not im.e_locacao("990401") and not im.e_locacao("")


def test_ler_usa_o_valor_da_nota_quando_falta_o_total():
    lido, probs = im.ler({"codigo_municipio": "3555406", "locacao": {}}, Decimal("1500.00"))
    assert probs == [] and lido is not None and lido.locacao is not None
    assert lido.locacao.valor_total == Decimal("1500.00")
    assert lido.locacao.copropriedade == Decimal("100.00")


# ── Pelo Emissor: a regra barra antes de assinar; a nota boa leva o grupo ─────────────────────

def test_emissor_leva_o_imovel_e_barra_o_redutor_no_comercial(pfx_teste, tmp_path, monkeypatch):
    from pynfsenacional import ConfigError, Emissor
    from pynfsenacional.sefin import RespostaSefin

    caminho, senha = pfx_teste
    enviados: list[str] = []

    class Fake:
        def verificar_dps(self, idd):
            return False

        def emitir(self, xml):
            enviados.append(xml)
            return RespostaSefin(ok=True, chave_acesso="33OK", numero_nfse="1",
                                 nfse_xml="<NFSe/>")

    def emissor(nbs: str) -> Emissor:
        d = copy.deepcopy(LOCACAO)
        d["servico"]["cNBS"] = nbs
        d["certificado"] = {"path": str(caminho), "senha": senha}
        e = Emissor(ClienteConfig.from_dict(d), ambiente="homologacao", out_dir=tmp_path)
        monkeypatch.setattr(e, "_sefin_client", lambda: Fake())
        return e

    nota = emissor("110021000").emitir(valor="1500.00", descricao="Aluguel", tomador=TOMADOR,
                                       imovel=APTO)
    assert nota.emitida and "<gAjusteBCLocImoveis>" in enviados[0]
    with pytest.raises(ConfigError, match="E0944"):
        emissor("110022000").emitir(valor="1500.00", descricao="Aluguel", tomador=TOMADOR,
                                    imovel=APTO)
    assert len(enviados) == 1
