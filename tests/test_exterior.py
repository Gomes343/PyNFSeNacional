"""Tomador no EXTERIOR e comércio exterior (§22).

O alvo é a DPS que o Emissor Web monta para uma exportação de serviço do Simples e o SEFIN
autorizou (tomador com NIF, ``endExt``, ``comExt`` com modo 4 e ``tribISSQN=3`` + ``cPaisResult``)
e a de um tomador SEM NIF com o ISS tributável. A sequência de elementos foi conferida contra as
duas notas reais (fora deste repositório); aqui os dados são fictícios. As regras são as do
Anexo I v1.01 (09/02/2026), aba "RN DPS_NFS-e".
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from conftest import CONFIG_VALIDA
from lxml import etree

from pynfsenacional import dps, exterior
from pynfsenacional.config import (
    LEIAUTE_NT009,
    LEIAUTE_PRODUCAO,
    ClienteConfig,
    validar_tomador,
)
from pynfsenacional.emissor import mesma_nota

NS = "{http://www.sped.fazenda.gov.br/nfse}"
XSD = Path(__file__).parent / "xsd"

ENDERECO_CR: dict[str, Any] = {
    "pais": "CR", "codigo_postal": "10101", "cidade": "San Pedro", "estado": "San José",
    "logradouro": "Avenida Central", "numero": "100", "complemento": "Oficina 2",
    "bairro": "Centro",
}
TOMADOR_NIF: dict[str, Any] = {"nif": "3101999999", "nome": "EXEMPLO S.R.L.",
                               "endereco": ENDERECO_CR}
TOMADOR_SEM_NIF: dict[str, Any] = {
    "motivo_sem_nif": "1", "nome": "EXAMPLE INC.",
    "endereco": {"pais": "US", "codigo_postal": "77001", "cidade": "Houston",
                 "estado": "Texas", "logradouro": "Main St", "numero": "10",
                 "bairro": "Main St"},
}
EXPORTACAO: dict[str, Any] = {"modo_prestacao": 4, "moeda": "220", "valor_moeda": "1000",
                              "exportacao": True}
TRANSFRONTEIRICO: dict[str, Any] = {"modo_prestacao": 1, "moeda": "220",
                                    "valor_moeda": "2540.00"}


def _cfg(**servico: Any) -> ClienteConfig:
    d = copy.deepcopy(CONFIG_VALIDA)
    d["servico"]["cNBS"] = "123019800"
    d["servico"].update(servico)
    return ClienteConfig.from_dict(d)


def _dps(tomador: dict[str, Any] | None = TOMADOR_NIF,
         comercio_exterior: dict[str, Any] | None = EXPORTACAO,
         leiaute: str = LEIAUTE_PRODUCAO, cfg: ClienteConfig | None = None) -> etree._Element:
    xml = dps.montar_dps(cfg or _cfg(), numero="7", valor=Decimal("5000.00"),
                         descricao="Psicoterapia on-line", tomador=tomador,
                         ambiente="producao", dh_emi="2026-11-19T10:00:00-03:00",
                         d_comp="2026-11-19", leiaute=leiaute,
                         comercio_exterior=comercio_exterior)
    return etree.fromstring(xml.encode())


def _seq(raiz: etree._Element, grupo: str) -> list[str]:
    el = raiz.find(f".//{NS}{grupo}")
    assert el is not None, grupo
    return [etree.QName(e).localname for e in el.iter() if isinstance(e.tag, str)]


def _texto(raiz: etree._Element, caminho: str) -> str | None:
    el = raiz.find(".//" + "/".join(NS + p for p in caminho.split("/")))
    return None if el is None else el.text


# ── A DPS ────────────────────────────────────────────────────────────────────────────────────

def test_exportacao_tem_a_sequencia_da_nota_autorizada():
    raiz = _dps()
    assert _seq(raiz, "toma") == [
        "toma", "NIF", "xNome", "end", "endExt", "cPais", "cEndPost", "xCidade",
        "xEstProvReg", "xLgr", "nro", "xCpl", "xBairro"]
    assert _seq(raiz, "comExt") == [
        "comExt", "mdPrestacao", "vincPrest", "tpMoeda", "vServMoeda", "mecAFComexP",
        "mecAFComexT", "movTempBens", "mdic"]
    assert _seq(raiz, "tribMun") == ["tribMun", "tribISSQN", "cPaisResult", "tpRetISSQN"]
    assert _texto(raiz, "tribMun/tribISSQN") == "3"
    assert _texto(raiz, "tribMun/cPaisResult") == "CR"


def test_comext_vem_entre_cserv_e_infocompl_com_os_padroes():
    raiz = _dps(cfg=_cfg(info_complementares="Pagamento por remessa internacional."))
    serv = [etree.QName(e).localname for e in raiz.find(f".//{NS}serv")]
    assert serv == ["locPrest", "cServ", "comExt", "infoCompl"]
    assert [e.text for e in raiz.find(f".//{NS}comExt")] == [
        "4", "0", "220", "1000.00", "01", "01", "1", "0"]


def test_tomador_sem_nif_e_iss_tributavel():
    raiz = _dps(TOMADOR_SEM_NIF, TRANSFRONTEIRICO)
    assert _seq(raiz, "toma")[:3] == ["toma", "cNaoNIF", "xNome"]
    assert _texto(raiz, "toma/cNaoNIF") == "1"
    assert _texto(raiz, "comExt/mdPrestacao") == "1"
    assert _seq(raiz, "tribMun") == ["tribMun", "tribISSQN", "tpRetISSQN"]
    assert _texto(raiz, "tribMun/tribISSQN") == "1"


def test_exportacao_pela_config_da_a_mesma_dps():
    pela_nota = etree.tostring(_dps())
    ce = {k: v for k, v in EXPORTACAO.items() if k != "exportacao"}
    pela_config = etree.tostring(_dps(comercio_exterior=ce,
                                      cfg=_cfg(tributos={"pTotTribSN": "6.00",
                                                         "tribISSQN": 3})))
    assert pela_nota == pela_config


def test_pais_do_resultado_declarado_vence_o_do_endereco():
    raiz = _dps(comercio_exterior={**EXPORTACAO, "pais_resultado": "pt"})
    assert _texto(raiz, "tribMun/cPaisResult") == "PT"


def test_nota_do_brasil_nao_muda():
    """Sem tomador do exterior e sem comércio exterior a DPS é a de antes (o golden e os hashes
    pinados de test_regime_regular cobrem o byte; aqui, que nada do exterior aparece)."""
    raiz = _dps({"cpf_cnpj": "11144477735", "nome": "FULANO"}, None)
    xml = etree.tostring(raiz).decode()
    for tag in ("NIF", "cNaoNIF", "endExt", "comExt", "cPaisResult"):
        assert f"<{tag}" not in xml and f":{tag}" not in xml


@pytest.mark.parametrize("leiaute", [LEIAUTE_PRODUCAO, LEIAUTE_NT009])
@pytest.mark.parametrize("tomador,ce", [(TOMADOR_NIF, EXPORTACAO),
                                        (TOMADOR_SEM_NIF, TRANSFRONTEIRICO)])
def test_passa_no_xsd_oficial(leiaute, tomador, ce):
    esquema = etree.XMLSchema(etree.parse(str(XSD / leiaute / "DPS_v1.01.xsd")))
    raiz = _dps(tomador, ce, leiaute)
    assert esquema.validate(raiz), [e.message for e in esquema.error_log]


# ── A validação (Anexo I) ───────────────────────────────────────────────────────────────────

def _problemas(tomador: dict[str, Any] | None = TOMADOR_NIF,
               ce: dict[str, Any] | None = EXPORTACAO, cnbs: str = "123019800",
               tributos: dict[str, Any] | None = None) -> str:
    return " | ".join(validar_tomador(tomador) + exterior.validar_comercio_exterior(
        ce, tomador, tributos or {"pTotTribSN": "6.00"}, cnbs))


def test_casos_validos_nao_tem_problema():
    assert _problemas() == ""
    assert _problemas(TOMADOR_SEM_NIF, TRANSFRONTEIRICO) == ""


@pytest.mark.parametrize("mexer,codigo", [
    ({"motivo_sem_nif": "0", "nif": None}, "E0226"),
    ({"nome": ""}, "E0233"),
    ({"endereco": None}, "E0242"),
    ({"endereco": {**ENDERECO_CR, "pais": "BR"}}, "E0242"),
    ({"endereco": {**ENDERECO_CR, "bairro": ""}}, "bairro"),
    ({"cpf_cnpj": "11144477735"}, "CPF/CNPJ E com NIF"),
    ({"motivo_sem_nif": "1"}, "um dos dois"),
])
def test_tomador_do_exterior(mexer, codigo):
    tom = {k: v for k, v in {**TOMADOR_NIF, **mexer}.items() if v is not None}
    assert codigo in _problemas(tom)


@pytest.mark.parametrize("mexer,codigo", [
    ({"modo_prestacao": 0}, "E0333"),
    ({"mec_prestador": "00"}, "E0341"),
    ({"mec_tomador": "00"}, "E0343"),
    ({"mov_temp_bens": 0}, "E0345"),
    ({"numero_di": "123456789012"}, "E0354"),
    ({"mov_temp_bens": 2}, "E0352"),
    ({"mov_temp_bens": 3}, "E0356"),
    ({"moeda": "US"}, "BACEN"),
    ({"valor_moeda": "0"}, "valor_moeda"),
    ({"pais_resultado": "BR"}, "E0590"),
])
def test_comercio_exterior(mexer, codigo):
    assert codigo in _problemas(ce={**EXPORTACAO, **mexer})


def test_tomador_do_exterior_exige_comext_e_nbs():
    assert "E0330" in _problemas(ce=None)
    assert "E0318" in _problemas(cnbs="")


def test_exportacao_pela_config_sem_comext_e_e0330():
    assert "E0330" in _problemas(None, None, tributos={"tribISSQN": 3})


def test_tomador_do_brasil_pode_exportar_com_o_pais_declarado():
    """Cenários 2 e 30 do Anexo I: tribISSQN=3 com tomador do Brasil é aceito, e o
    cPaisResult (E0590) tem de vir declarado."""
    tom = {"cpf_cnpj": "11144477735", "nome": "FULANO"}
    assert "E0590" in _problemas(tom)
    assert _problemas(tom, {**EXPORTACAO, "pais_resultado": "PT"}) == ""


def test_exportacao_nao_tem_iss_retido():
    assert "tpRetISSQN" in _problemas(tributos={"tpRetISSQN": 2})


# ── A nota achada na SEFIN é esta? (contador de nDPS) ──────────────────────────────────────

def _nota(toma: str) -> str:
    return (f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infDPS><toma>{toma}'
            f"<xNome>X</xNome></toma><valores><vServPrest><vServ>5000.00</vServ></vServPrest>"
            f"</valores></infDPS></NFSe>")


def test_mesma_nota_reconhece_o_nif():
    assert mesma_nota(_nota("<NIF>3101999999</NIF>"), "5000", TOMADOR_NIF) is True
    assert mesma_nota(_nota("<NIF>3101000000</NIF>"), "5000", TOMADOR_NIF) is False
    assert mesma_nota(_nota("<cNaoNIF>1</cNaoNIF>"), "5000", TOMADOR_SEM_NIF) is True
    # Um CPF nunca casa com um NIF de mesmos dígitos.
    assert mesma_nota(_nota("<NIF>11144477735</NIF>"), "5000",
                      {"cpf_cnpj": "11144477735", "nome": "F"}) is False
