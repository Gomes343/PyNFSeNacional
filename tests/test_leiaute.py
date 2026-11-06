"""Os dois leiautes do XSD da DPS (§19): cada DPS que a lib monta, contra o esquema OFICIAL.

O SEFIN de produção aplica o pacote de 09/02/2026; a homologação (produção restrita) aplica o de
20/10/2026 (NT 009) desde 31/10/2026. Os dois têm a mesma `versao="1.01"`. Os esquemas estão em
`tests/xsd/` (ver o README de lá). Aqui a prova é de esquema: uma DPS que não passa no XSD é E1235
no SEFIN, sem chegar a regra de negócio nenhuma.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from conftest import CONFIG_VALIDA
from lxml import etree
from test_regime_regular import REGULAR, TOMADOR_PJ

from pynfsenacional import dps
from pynfsenacional.config import (
    LEIAUTE_NT009,
    LEIAUTE_PRODUCAO,
    LEIAUTES,
    ClienteConfig,
    leiaute_do_ambiente,
)
from pynfsenacional.emissor import _dica_leiaute

NS = "http://www.sped.fazenda.gov.br/nfse"
XSD = Path(__file__).parent / "xsd"
_ESQUEMAS: dict[str, etree.XMLSchema] = {}


def _esquema(leiaute: str) -> etree.XMLSchema:
    if leiaute not in _ESQUEMAS:
        _ESQUEMAS[leiaute] = etree.XMLSchema(etree.parse(str(XSD / leiaute / "DPS_v1.01.xsd")))
    return _ESQUEMAS[leiaute]


def _erros(xml: str, leiaute: str) -> list[str]:
    esquema = _esquema(leiaute)
    if esquema.validate(etree.fromstring(xml.encode())):
        return []
    return [e.message for e in esquema.error_log]


# ── As configs ───────────────────────────────────────────────────────────────────────────────

def _simples(**servico: Any) -> dict[str, Any]:
    d = copy.deepcopy(CONFIG_VALIDA)
    d["servico"].update(servico)
    return d


def _mei() -> dict[str, Any]:
    d = copy.deepcopy(CONFIG_VALIDA)
    d["prestador"]["regime"] = {"opSimpNac": 2, "regEspTrib": 0}
    d["servico"]["tributos"] = {"indTotTrib": 0}
    return d


def _com_im() -> dict[str, Any]:
    d = _simples(info_complementares="Sem retencao de IRRF.")
    d["prestador"]["inscricao_municipal"] = "1234567"
    return d


def _regular(**servico: Any) -> dict[str, Any]:
    d = copy.deepcopy(REGULAR)
    for k, v in servico.items():
        if k == "tributos":
            d["servico"]["tributos"] = {**d["servico"]["tributos"], **v}
        else:
            d["servico"][k] = v
    return d


# O grupo IBS/CBS no Simples: o que passa a ser obrigatório em 01/01/2027 (§8). Os códigos são os
# do Anexo VIII para "demais serviços" (01.01: NBS 1.1502.10.00, cIndOp 100301).
IBSCBS_SIMPLES = {"cIndOp": "100301", "CST": "000", "cClassTrib": "000001", "indFinal": "0"}

EVENTO_ENDERECO = {"nome": "Torneio de exemplo", "inicio": "2026-11-04", "fim": "2026-11-04",
                   "endereco": {"cep": "01310-100", "logradouro": "AVENIDA PAULISTA",
                                "numero": "1000", "complemento": "SALA 1", "bairro": "BELA VISTA"}}
EVENTO_ID = {"nome": "Campeonato de teste", "inicio": "2026-10-01", "fim": "2026-10-31",
             "id": "EVT-0001"}

CONFIGS = {
    "simples": _simples(),
    "simples_im_infocompl": _com_im(),
    "simples_ibscbs": _simples(ibscbs=IBSCBS_SIMPLES, cNBS="115021000"),
    "mei": _mei(),
    "regular_ibscbs": _regular(),
    "regular_sem_indfinal": _regular(ibscbs={"cIndOp": "050101", "CST": "000",
                                             "cClassTrib": "000001"}),
    "regular_retido": _regular(tributos={"tpRetISSQN": 2}),
    # ME/EPP com o ISS pelo Simples e ISS retido: a alíquota do município vai no tribMun (§15).
    "simples_retido_paliq": _simples(tributos={"pTotTribSN": "6.00", "tpRetISSQN": 2,
                                               "pAliq": "2.01"}),
    # Item 12 (competições esportivas): grupo Atividade/Evento, local por endereço ou por id.
    "simples_evento_endereco": _simples(cTribNac="121101", cTribMun="", evento=EVENTO_ENDERECO),
    "simples_evento_id": _simples(cTribNac="121101", cTribMun="", evento=EVENTO_ID,
                                  info_complementares="Sem retencao de IRRF."),
}
TOMADORES = {
    "sem_tomador": None,
    "cpf": {"cpf_cnpj": "11144477735", "nome": "FULANO DE TAL"},
    "pj_completo": {**TOMADOR_PJ, "fone": "11999998888", "email": "a@b.com", "im": "998877"},
}


def _montar(cfg: str, tomador: str, leiaute: str, ambiente: str = "producao") -> str:
    return dps.montar_dps(
        ClienteConfig.from_dict(copy.deepcopy(CONFIGS[cfg])), numero="12", serie="70000",
        valor="1262.90", descricao="Servico de teste", tomador=TOMADORES[tomador],
        ambiente=ambiente, dh_emi="2026-10-31T10:00:00-03:00", d_comp="2026-10-31",
        leiaute=leiaute,
    )


# ── A matriz: toda variante passa no esquema do SEU leiaute ──────────────────────────────────

@pytest.mark.parametrize("leiaute", LEIAUTES)
@pytest.mark.parametrize("tomador", sorted(TOMADORES))
@pytest.mark.parametrize("cfg", sorted(CONFIGS))
def test_dps_passa_no_xsd_oficial_do_leiaute(cfg, tomador, leiaute):
    assert _erros(_montar(cfg, tomador, leiaute), leiaute) == []


@pytest.mark.parametrize("cfg", sorted(CONFIGS))
def test_toda_config_da_matriz_e_valida(cfg):
    """A matriz só prova algo se as configs passarem no validar() — senão a DPS nunca sairia."""
    assert ClienteConfig.from_dict(copy.deepcopy(CONFIGS[cfg])).validar() == []


def test_grupo_ibscbs_sem_nbs_e_recusado_e0322():
    d = _simples(ibscbs=IBSCBS_SIMPLES)
    assert any("E0322" in p for p in ClienteConfig.from_dict(d).validar())


@pytest.mark.parametrize("cfg", ["simples", "mei", "regular_ibscbs"])
def test_cada_leiaute_e_recusado_pelo_esquema_do_outro(cfg):
    """O controle negativo: se os dois passassem nos dois esquemas, a troca não provaria nada."""
    assert any("finNFSe" in e for e in _erros(_montar(cfg, "cpf", LEIAUTE_NT009),
                                              LEIAUTE_PRODUCAO))
    assert any("cLocEmi" in e for e in _erros(_montar(cfg, "cpf", LEIAUTE_PRODUCAO),
                                              LEIAUTE_NT009))


# ── O que muda na NT 009 ─────────────────────────────────────────────────────────────────────

def _inf(xml: str) -> etree._Element:
    inf = etree.fromstring(xml.encode()).find(f"{{{NS}}}infDPS")
    assert inf is not None
    return inf


def _nomes(el: etree._Element | None) -> list[str]:
    assert el is not None
    return [etree.QName(c).localname for c in el]


def _achar(inf: etree._Element, caminho: str) -> etree._Element | None:
    return inf.find("/".join(f"{{{NS}}}{p}" for p in caminho.split("/")))


def test_nt009_finnfse_vai_para_o_infdps_mesmo_sem_o_grupo():
    inf = _inf(_montar("simples", "cpf", LEIAUTE_NT009))
    nomes = _nomes(inf)
    assert nomes[nomes.index("tpEmit") + 1] == "finNFSe"
    assert nomes[nomes.index("finNFSe") + 1] == "cLocEmi"
    assert _achar(inf, "finNFSe").text == "0"
    assert "IBSCBS" not in nomes


def test_nt009_xdescserv_vai_para_depois_do_cnbs():
    inf = _inf(_montar("regular_ibscbs", "cpf", LEIAUTE_NT009))
    assert _nomes(_achar(inf, "serv/cServ")) == ["cTribNac", "cTribMun", "cNBS", "xDescServ"]
    inf = _inf(_montar("regular_ibscbs", "cpf", LEIAUTE_PRODUCAO))
    assert _nomes(_achar(inf, "serv/cServ")) == ["cTribNac", "cTribMun", "xDescServ", "cNBS"]


def test_nt009_cst_e_cclasstrib_sobem_para_trib():
    inf = _inf(_montar("regular_ibscbs", "cpf", LEIAUTE_NT009))
    assert _nomes(_achar(inf, "IBSCBS")) == ["indFinal", "cIndOp", "indDest", "valores"]
    trib = _achar(inf, "IBSCBS/valores/trib")
    assert [(etree.QName(c).localname, c.text) for c in trib] == [
        ("CST", "000"), ("cClassTrib", "000001")]          # sem gIBSCBS (só crédito/diferimento)


def test_producao_segue_com_o_grupo_de_antes():
    inf = _inf(_montar("regular_ibscbs", "cpf", LEIAUTE_PRODUCAO))
    assert "finNFSe" not in _nomes(inf)
    assert _nomes(_achar(inf, "IBSCBS")) == ["finNFSe", "indFinal", "cIndOp", "indDest", "valores"]
    assert _nomes(_achar(inf, "IBSCBS/valores/trib/gIBSCBS")) == ["CST", "cClassTrib"]


def test_cnpj_alfanumerico_so_passa_no_esquema_da_nt009():
    """O CNPJ alfanumérico (§1 da NT 009) só existe no esquema novo; o de produção é [0-9]{14}."""
    d = copy.deepcopy(CONFIG_VALIDA)
    d["prestador"]["cnpj"] = "12ABC34501DE35"
    cfg = ClienteConfig.from_dict(d)
    xml = {lt: dps.montar_dps(cfg, numero="1", valor="1", descricao="x", tomador=None,
                              ambiente="producao", leiaute=lt) for lt in LEIAUTES}
    assert _erros(xml[LEIAUTE_NT009], LEIAUTE_NT009) == []
    assert _erros(xml[LEIAUTE_PRODUCAO], LEIAUTE_PRODUCAO) != []


# ── Quem escolhe o leiaute ───────────────────────────────────────────────────────────────────

def test_leiaute_padrao_e_o_do_ambiente():
    assert leiaute_do_ambiente("producao") == LEIAUTE_PRODUCAO
    assert leiaute_do_ambiente("homologacao") == LEIAUTE_NT009
    cfg = ClienteConfig.from_dict(copy.deepcopy(CONFIG_VALIDA))
    for ambiente in ("producao", "homologacao"):
        xml = dps.montar_dps(cfg, numero="1", valor="1", descricao="x", tomador=None,
                             ambiente=ambiente)
        assert _erros(xml, leiaute_do_ambiente(ambiente)) == []


def test_config_forca_o_leiaute():
    """A virada: quando a produção trocar de pacote antes de a lib trocar o padrão."""
    d = {**copy.deepcopy(CONFIG_VALIDA), "leiaute": LEIAUTE_NT009}
    cfg = ClienteConfig.from_dict(d)
    assert cfg.validar() == []
    xml = dps.montar_dps(cfg, numero="1", valor="1", descricao="x", tomador=None,
                         ambiente="producao")
    assert _erros(xml, LEIAUTE_NT009) == []


def test_leiaute_desconhecido_e_recusado():
    d = {**copy.deepcopy(CONFIG_VALIDA), "leiaute": "2027"}
    cfg = ClienteConfig.from_dict(d)
    assert any("leiaute inválido" in p for p in cfg.validar())
    with pytest.raises(ValueError, match="leiaute inválido"):
        dps.montar_dps(cfg, numero="1", valor="1", descricao="x", tomador=None,
                       ambiente="producao")


# ── A virada da produção: o erro diz qual leiaute configurar ─────────────────────────────────

_E1235_PROD = ("E1235", "Falha no esquema XML: The element 'infDPS' has invalid child element "
               "'cLocEmi'. List of possible elements expected: 'cMotivoEmisTI, finNFSe'.")


def test_e1235_do_finnfse_aponta_o_outro_leiaute():
    codigo, msg = _E1235_PROD
    dica = _dica_leiaute(f"[{codigo}] {msg}", codigo, LEIAUTE_PRODUCAO)
    assert dica is not None and dica.startswith("[E1235] Falha no esquema")  # o código na frente
    assert f'"leiaute": "{LEIAUTE_NT009}"' in dica
    dica = _dica_leiaute("[E1235] invalid child element 'finNFSe'", "E1235", LEIAUTE_NT009)
    assert dica is not None and f'"leiaute": "{LEIAUTE_PRODUCAO}"' in dica


@pytest.mark.parametrize("codigo,msg", [
    ("E1235", "[E1235] invalid child element 'IM'"),     # outro erro de esquema: sem dica
    ("E0322", "[E0322] finNFSe"),                        # outro código: sem dica
    (None, None),
])
def test_sem_dica_fora_do_caso(codigo, msg):
    assert _dica_leiaute(msg, codigo, LEIAUTE_PRODUCAO) == msg
