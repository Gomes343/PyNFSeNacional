"""Regime Regular (Não Optante), ISS retido pelo tomador e o grupo IBS/CBS — §8, §12, §14, §15.

O alvo é a DPS que o PRÓPRIO portal do governo (EmissorWeb) monta para um prestador do Lucro
Presumido e que o SEFIN autorizou em produção (cStat 100). O gabarito abaixo é essa DPS com os
identificadores trocados por dados fictícios — a ESTRUTURA e os códigos fiscais são os dela.

E o controle negativo: nada disso pode mexer na DPS do Simples e do MEI. Os hashes pinados em
`HASHES_SEM_REGIME_REGULAR` foram tirados do código ANTES das funções novas existirem.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest
from conftest import CONFIG_VALIDA
from lxml import etree

from pynfsenacional import dps
from pynfsenacional.config import ClienteConfig, ConfigError, validar_retencao
from pynfsenacional.emissor import Emissor

NS = "http://www.sped.fazenda.gov.br/nfse"

# ── Config de um prestador do Lucro Presumido (fictício) ─────────────────────────────────────
REGULAR: dict[str, Any] = {
    **copy.deepcopy(CONFIG_VALIDA),
    "prestador": {
        "cnpj": "11222333000181",
        "codigo_municipio": "3304557",
        # Sem regApTribSN de propósito: o default da dataclass (1) NÃO pode vazar (E0162).
        "regime": {"opSimpNac": 1, "regEspTrib": 0},
    },
    "servico": {
        "codigo_municipio_prestacao": "3304557",
        "cTribNac": "140101",
        "cTribMun": "068",
        "cNBS": "120015000",
        "tributos": {
            "piscofins_cst": "00",
            "tpRetPisCofins": "0",
            "pTotTrib": {"pTotTribFed": "11.33", "pTotTribEst": "0", "pTotTribMun": 3},
        },
        "ibscbs": {"cIndOp": "050101", "CST": "000", "cClassTrib": "000001", "indFinal": "0"},
    },
}

TOMADOR_PJ = {
    "cpf_cnpj": "11444777000161",
    "nome": "INDUSTRIA EXEMPLO LTDA",
    "endereco": {"cMun": "3550308", "cep": "01001000", "logradouro": "RUA EXEMPLO",
                 "numero": "100", "complemento": "SALA 1", "bairro": "CENTRO"},
}

# A DPS do portal (estrutura e códigos reais; identificadores fictícios). O que o portal manda e
# esta biblioteca NÃO manda: `prest/fone` e `prest/email` — opcionais, puxados do cadastro pelo
# próprio portal; o SEFIN preenche o emitente na NFS-e a partir do CNC de qualquer forma.
GABARITO_PORTAL = f"""<infDPS xmlns="{NS}" Id="DPS330455721122233300018170000000000000000012">
<tpAmb>1</tpAmb><dhEmi>2026-10-16T09:30:00-03:00</dhEmi><verAplic>EmissorWeb_1.6.0.0</verAplic>
<serie>70000</serie><nDPS>12</nDPS><dCompet>2026-10-16</dCompet><tpEmit>1</tpEmit>
<cLocEmi>3304557</cLocEmi>
<prest><CNPJ>11222333000181</CNPJ><regTrib><opSimpNac>1</opSimpNac><regEspTrib>0</regEspTrib></regTrib></prest>
<toma><CNPJ>11444777000161</CNPJ><xNome>INDUSTRIA EXEMPLO LTDA</xNome>
<end><endNac><cMun>3550308</cMun><CEP>01001000</CEP></endNac><xLgr>RUA EXEMPLO</xLgr><nro>100</nro>
<xCpl>SALA 1</xCpl><xBairro>CENTRO</xBairro></end></toma>
<serv><locPrest><cLocPrestacao>3304557</cLocPrestacao></locPrest>
<cServ><cTribNac>140101</cTribNac><cTribMun>068</cTribMun>
<xDescServ>Manutencao de equipamento industrial.</xDescServ>
<cNBS>120015000</cNBS></cServ></serv>
<valores><vServPrest><vServ>250.00</vServ></vServPrest>
<trib><tribMun><tribISSQN>1</tribISSQN><tpRetISSQN>1</tpRetISSQN></tribMun>
<tribFed><piscofins><CST>00</CST><tpRetPisCofins>0</tpRetPisCofins></piscofins></tribFed>
<totTrib><pTotTrib><pTotTribFed>11.33</pTotTribFed><pTotTribEst>0.00</pTotTribEst>
<pTotTribMun>3.00</pTotTribMun></pTotTrib></totTrib></trib></valores>
<IBSCBS><finNFSe>0</finNFSe><indFinal>0</indFinal><cIndOp>050101</cIndOp><indDest>0</indDest>
<valores><trib><gIBSCBS><CST>000</CST><cClassTrib>000001</cClassTrib></gIBSCBS></trib></valores>
</IBSCBS></infDPS>"""


def _c14n(el: etree._Element) -> bytes:
    return etree.tostring(el, method="c14n", exclusive=True)


def _sem_espacos(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode(), etree.XMLParser(remove_blank_text=True))


def _montar(cfgd: dict[str, Any], tomador: dict[str, Any] | None = TOMADOR_PJ,
            **kw: Any) -> etree._Element:
    base = dict(numero="12", serie="70000", valor=250.0,
                descricao="Manutencao de equipamento industrial.", tomador=tomador,
                ambiente="producao", dh_emi="2026-10-16T09:30:00-03:00", d_comp="2026-10-16",
                ver_aplic="EmissorWeb_1.6.0.0")
    base.update(kw)
    xml = dps.montar_dps(ClienteConfig.from_dict(cfgd), **base)
    inf = etree.fromstring(xml.encode()).find(f"{{{NS}}}infDPS")
    assert inf is not None
    return inf


def _filhos(el: etree._Element | None) -> list[str]:
    assert el is not None
    return [etree.QName(c).localname for c in el]


def _achar(inf: etree._Element, caminho: str) -> etree._Element | None:
    return inf.find("/".join(f"{{{NS}}}{p}" for p in caminho.split("/")))


def _pares(el: etree._Element | None) -> list[tuple[str, str | None]]:
    assert el is not None
    return [(etree.QName(c).localname, c.text) for c in el]


def _mutar(**servico: Any) -> dict[str, Any]:
    d = copy.deepcopy(REGULAR)
    for k, v in servico.items():
        if k == "tributos":
            d["servico"]["tributos"] = {**d["servico"]["tributos"], **v}
        else:
            d["servico"][k] = v
    return d


# ── A DPS do portal ───────────────────────────────────────────────────────────────────────────

def test_dps_do_regime_regular_bate_com_a_do_portal_byte_a_byte():
    """C14N do infDPS idêntico ao da DPS que o portal montou e o SEFIN autorizou."""
    assert _c14n(_montar(REGULAR)) == _c14n(_sem_espacos(GABARITO_PORTAL))


def test_nao_optante_omite_regaptribsn():
    """E0162: regApTribSN é só do ME/EPP. O default 1 da dataclass não pode vazar."""
    d = copy.deepcopy(REGULAR)
    d["prestador"]["regime"] = {"opSimpNac": 1, "regApTribSN": 1, "regEspTrib": 0}
    reg = _achar(_montar(d), "prest/regTrib")
    assert _filhos(reg) == ["opSimpNac", "regEspTrib"]


def test_cnbs_vem_depois_do_xdescserv_e_vazio_omite():
    assert _filhos(_achar(_montar(REGULAR), "serv/cServ")) == [
        "cTribNac", "cTribMun", "xDescServ", "cNBS"]
    assert "cNBS" not in _filhos(_achar(_montar(_mutar(cNBS="")), "serv/cServ"))


def test_ibscbs_e_o_ultimo_filho_do_infdps_na_ordem_do_xsd():
    inf = _montar(REGULAR)
    assert _filhos(inf)[-2:] == ["valores", "IBSCBS"]
    assert _filhos(_achar(inf, "IBSCBS")) == ["finNFSe", "indFinal", "cIndOp", "indDest", "valores"]
    assert _filhos(_achar(inf, "IBSCBS/valores/trib/gIBSCBS")) == ["CST", "cClassTrib"]


def test_ibscbs_sem_indfinal_omite_o_elemento():
    ibs = {"cIndOp": "050101", "CST": "000", "cClassTrib": "000001"}
    assert _filhos(_achar(_montar(_mutar(ibscbs=ibs)), "IBSCBS")) == [
        "finNFSe", "cIndOp", "indDest", "valores"]


def test_ptottrib_formata_duas_casas():
    tot = _achar(_montar(REGULAR), "valores/trib/totTrib/pTotTrib")
    assert _pares(tot) == [
        ("pTotTribFed", "11.33"), ("pTotTribEst", "0.00"), ("pTotTribMun", "3.00")]


def test_nao_optante_sem_ptottrib_segue_com_indtottrib():
    d = copy.deepcopy(REGULAR)
    del d["servico"]["tributos"]["pTotTrib"]
    assert _filhos(_achar(_montar(d), "valores/trib/totTrib")) == ["indTotTrib"]


def test_tpretpiscofins_vem_depois_do_cst():
    assert _filhos(_achar(_montar(REGULAR), "valores/trib/tribFed/piscofins")) == [
        "CST", "tpRetPisCofins"]


def test_iss_retido_pelo_tomador():
    """§15: a retenção é da operação — a config da nota leva tpRetISSQN=2."""
    inf = _montar(_mutar(tributos={"tpRetISSQN": 2}))
    tm = _achar(inf, "valores/trib/tribMun")
    assert _pares(tm) == [
        ("tribISSQN", "1"), ("tpRetISSQN", "2")]   # sem pAliq: E0617 (convênio ativo)


# ── Controle negativo: Simples e MEI byte-a-byte iguais aos de antes ─────────────────────────

_TOM_CPF = {"cpf_cnpj": "11144477735", "nome": "FULANO DE TAL"}
_TOM_COMPLETO = {"cpf_cnpj": "11222333000181", "nome": "EMPRESA X", "email": "a@b.com",
                 "fone": "11999998888",
                 "endereco": {"cep": "01001000", "logradouro": "PRACA DA SE", "numero": "1",
                              "bairro": "SE", "cMun": "3550308"}}


def _cfg_mei() -> dict[str, Any]:
    d = copy.deepcopy(CONFIG_VALIDA)
    d["prestador"]["regime"] = {"opSimpNac": 2, "regEspTrib": 0}
    d["servico"]["tributos"] = {"indTotTrib": 0}
    return d


def _cfg_cst00() -> dict[str, Any]:
    d = copy.deepcopy(CONFIG_VALIDA)
    d["servico"]["tributos"]["piscofins_cst"] = "00"
    return d


# sha256 do C14N exclusivo do <DPS> inteiro, tirado do código de ANTES (v1.0.0, 18/10/2026).
HASHES_SEM_REGIME_REGULAR = {
    ("simples", "sem_tomador"): "e84f0e549229a95a990e73603cbcd6aae2492d0b3ab75eb109985fae689b7654",
    ("simples", "cpf"): "221df992f717bfcea7fb49f2f461726a26e5f846216e448e96132a263c2e1473",
    ("simples", "cnpj_completo"):
        "fbfc74fddb7fc670f19ddfbcd746d458ca21cebdd4f24945c296914b9138882c",
    ("mei", "sem_tomador"): "ec9b320d80fdcae6616de70d0dce4936455ec2be3d521622dc695c6ef341b74e",
    ("mei", "cpf"): "8fe67eb992ec5ed6a4458135525df83faf4bfdce7cfdeaa0183c72bdccf839e1",
    ("mei", "cnpj_completo"): "d4a25695b6326aa634c635ea4c5cc3b5db959ee67d8b750959a3c348edb98be4",
    ("simples_cst00", "sem_tomador"):
        "d90159a9da68dc6b737bc55b80d00de92667cc1f3de279a9049aa42ae1cafaff",
    ("simples_cst00", "cpf"): "af433d6f3eeb806584848086db187f1237748741ea3dd626d4ae326c898860c7",
    ("simples_cst00", "cnpj_completo"):
        "56f991c94463f3be8cce9f5d2e0e0d7b3fe0e6b31c5b24533dfe1e6f438cfab4",
}


@pytest.mark.parametrize("chave", sorted(HASHES_SEM_REGIME_REGULAR))
def test_simples_e_mei_saem_identicos_aos_de_antes(chave):
    cfgs = {"simples": CONFIG_VALIDA, "mei": _cfg_mei(), "simples_cst00": _cfg_cst00()}
    toms = {"sem_tomador": None, "cpf": _TOM_CPF, "cnpj_completo": _TOM_COMPLETO}
    regime, tom = chave
    xml = dps.montar_dps(ClienteConfig.from_dict(cfgs[regime]), numero="7", valor=1262.9,
                         descricao="Servico de teste", tomador=toms[tom], ambiente="producao",
                         serie="2", dh_emi="2026-10-18T10:00:00-03:00", d_comp="2026-10-18",
                         ver_aplic="PyNFSeNacional-0.1")
    obtido = hashlib.sha256(_c14n(etree.fromstring(xml.encode()))).hexdigest()
    assert obtido == HASHES_SEM_REGIME_REGULAR[chave]


# ── Validação (E-codes que dá para pegar antes do SEFIN) ─────────────────────────────────────

def _problemas(d: dict[str, Any]) -> list[str]:
    return ClienteConfig.from_dict(d).validar()


def test_config_do_regime_regular_e_valida():
    assert _problemas(REGULAR) == []


@pytest.mark.parametrize("mutacao, trecho", [
    ({"cNBS": "12001500"}, "cNBS"),
    ({"tributos": {"tpRetPisCofins": "10"}}, "tpRetPisCofins"),
    ({"tributos": {"piscofins_cst": "01", "tpRetPisCofins": None}}, "E0698"),
    ({"tributos": {"pTotTrib": {"pTotTribFed": "11.33", "pTotTribMun": "3"}}}, "pTotTribEst"),
    ({"tributos": {"pTotTrib": {"pTotTribFed": "101", "pTotTribEst": "0",
                                "pTotTribMun": "3"}}}, "E0706"),
    ({"tributos": {"tpRetISSQN": 3}}, "intermediário"),
    ({"tributos": {"tpRetISSQN": 9}}, "tpRetISSQN"),
    ({"ibscbs": {"CST": "000", "cClassTrib": "000001"}}, "cIndOp"),
    ({"ibscbs": {"cIndOp": "050101", "CST": "0", "cClassTrib": "000001"}}, "CST"),
    ({"ibscbs": {"cIndOp": "050101", "CST": "000", "cClassTrib": "000001",
                 "indDest": "1"}}, "indDest"),
    ({"ibscbs": {"cIndOp": "050101", "CST": "000", "cClassTrib": "000001",
                 "finNFSe": "1"}}, "finNFSe"),
    ({"ibscbs": {"cIndOp": "050101", "CST": "000", "cClassTrib": "000001",
                 "tpEnteGov": "1"}}, "tpEnteGov"),
])
def test_validar_recusa(mutacao, trecho):
    d = _mutar(**mutacao)
    tributos = d["servico"]["tributos"]
    for k in [k for k, v in tributos.items() if v is None]:
        del tributos[k]
    problemas = _problemas(d)
    assert any(trecho in p for p in problemas), problemas


def test_ptottrib_so_para_nao_optante():
    """Para o ME/EPP o caminho é o pTotTribSN; o MEI é isento (Decreto 8.264/2014)."""
    d = copy.deepcopy(CONFIG_VALIDA)
    d["servico"]["tributos"]["pTotTrib"] = {"pTotTribFed": "1", "pTotTribEst": "0",
                                            "pTotTribMun": "2"}
    assert any("pTotTrib" in p for p in _problemas(d))


@pytest.mark.parametrize("regime, ecode", [
    ({"opSimpNac": 2, "regEspTrib": 0}, "E0583"),            # MEI não sofre retenção
    ({"opSimpNac": 1, "regEspTrib": 1}, "E0588"),            # regime especial
    ({"opSimpNac": 3, "regApTribSN": 1, "regEspTrib": 0}, "E0621"),  # ME/EPP pede pAliq
])
def test_retencao_proibida_ou_nao_coberta(regime, ecode):
    d = _mutar(tributos={"tpRetISSQN": 2, "pTotTribSN": "6.00"})
    d["prestador"]["regime"] = regime
    if regime["opSimpNac"] != 1:
        del d["servico"]["tributos"]["pTotTrib"]
    assert any(ecode in p for p in _problemas(d))


def test_retencao_com_servico_imune_e0580():
    d = _mutar(tributos={"tpRetISSQN": 2, "tribISSQN": 2})
    assert any("E0580" in p for p in _problemas(d))


# ── Retenção × tomador (E0204 / E0237) ────────────────────────────────────────────────────────

def _retida() -> ClienteConfig:
    return ClienteConfig.from_dict(_mutar(tributos={"tpRetISSQN": 2}))


def test_retencao_exige_tomador_identificado_e0204():
    assert any("E0204" in p for p in validar_retencao(_retida(), None))


def test_retencao_exige_endereco_completo_do_tomador_e0237():
    sem_bairro = copy.deepcopy(TOMADOR_PJ)
    del sem_bairro["endereco"]["bairro"]
    problemas = validar_retencao(_retida(), sem_bairro)
    assert any("E0237" in p and "bairro" in p for p in problemas)
    assert "RUA EXEMPLO" not in " ".join(problemas)       # nome do campo, nunca o valor


def test_retencao_com_tomador_completo_passa():
    assert validar_retencao(_retida(), TOMADOR_PJ) == []


def test_sem_retencao_nao_exige_endereco():
    assert validar_retencao(ClienteConfig.from_dict(REGULAR), {"cpf_cnpj": "11444777000161",
                                                               "nome": "X"}) == []


def test_emissor_recusa_antes_de_tocar_o_sefin(tmp_path):
    """A recusa sai do validar — antes do certificado e do transporte (o .pfx nem existe)."""
    em = Emissor(_retida(), ambiente="homologacao", out_dir=tmp_path)
    with pytest.raises(ConfigError, match="E0237"):
        em.emitir(valor=250.0, descricao="x", tomador={"cpf_cnpj": "11444777000161",
                                                        "nome": "INDUSTRIA EXEMPLO LTDA"},
                  numero="1")
