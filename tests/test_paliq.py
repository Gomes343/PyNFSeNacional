"""`pAliq` — a alíquota do ISS na DPS (docs/conhecimento-fiscal.md §15).

O ME/EPP com o ISS pelo Simples e ISS RETIDO tem de informar a alíquota (E0621, mínimo 1,8%:
E0628); sem retenção ela é proibida (E0625). Sem `pAliq` a DPS não muda um byte."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from conftest import CONFIG_VALIDA
from lxml import etree

from pynfsenacional import dps
from pynfsenacional.config import ClienteConfig

NS = "{http://www.sped.fazenda.gov.br/nfse}"
TOMADOR = {"cpf_cnpj": "11222333000181", "nome": "TOMADOR TESTE LTDA",
           "endereco": {"cep": "01310100", "logradouro": "AVENIDA PAULISTA", "numero": "1000",
                        "bairro": "BELA VISTA", "cMun": "3550308"}}


def _cfg(**tributos: Any) -> dict[str, Any]:
    d = copy.deepcopy(CONFIG_VALIDA)
    d["servico"]["tributos"] = {"pTotTribSN": "6.00", **tributos}
    return d


def _problemas(d: dict[str, Any]) -> list[str]:
    return ClienteConfig.from_dict(d).validar()


def _tribmun(d: dict[str, Any]) -> list[tuple[str, str]]:
    xml = dps.montar_dps(ClienteConfig.from_dict(d), numero="1", valor="100", descricao="x",
                         tomador=TOMADOR, ambiente="homologacao",
                         dh_emi="2026-11-05T10:00:00-03:00", d_comp="2026-11-05")
    tm = etree.fromstring(xml.encode()).find(f".//{NS}tribMun")
    return [(el.tag.replace(NS, ""), el.text or "") for el in tm]


def test_retido_com_paliq_e_valido_e_vai_depois_do_tpretissqn():
    d = _cfg(tpRetISSQN=2, pAliq="2,01")
    assert not [p for p in _problemas(d) if "pAliq" in p or "E06" in p]
    assert _tribmun(d) == [("tribISSQN", "1"), ("tpRetISSQN", "2"), ("pAliq", "2.01")]


def test_retido_sem_paliq_e_e0621():
    assert any("E0621" in p for p in _problemas(_cfg(tpRetISSQN=2)))


def test_abaixo_do_minimo_e_e0628():
    assert any("E0628" in p for p in _problemas(_cfg(tpRetISSQN=2, pAliq="1.5")))


def test_sem_retencao_paliq_e_proibida_e0625():
    assert any("E0625" in p for p in _problemas(_cfg(pAliq="2")))


@pytest.mark.parametrize("valor, trecho", [("abc", "não é numérico"), ("5.5", "máximo de 5%")])
def test_valor_invalido(valor, trecho):
    assert any(trecho in p for p in _problemas(_cfg(tpRetISSQN=2, pAliq=valor)))


def test_sem_paliq_a_dps_nao_muda():
    assert _tribmun(_cfg()) == [("tribISSQN", "1"), ("tpRetISSQN", "1")]
