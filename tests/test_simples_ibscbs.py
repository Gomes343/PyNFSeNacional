"""O Simples Nacional no IBS/CBS (NT 009 §2.4; docs §8): `regApIBSCBSSN` e `cAtvSN`.

Os dois campos só existem no leiaute `nt009-sn` (Anexo VI v1.04.01), que nenhum pacote OFICIAL de
esquemas publicou até 17/11/2026: ele só entra quando a config o força. O esquema de
`tests/xsd/nt009-sn/` é o de 20/10/2026 com os dois elementos nas posições do Anexo VI (ver o
README de lá) — prova a ordem, não substitui o pacote oficial.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from conftest import CONFIG_VALIDA
from lxml import etree

from pynfsenacional import dps
from pynfsenacional.config import (
    ATIVIDADES_SN_NFSE,
    LEIAUTE_NT009,
    LEIAUTE_NT009_SN,
    LEIAUTE_PRODUCAO,
    ClienteConfig,
    atividade_sn,
)
from pynfsenacional.emissor import _dica_leiaute

NS = "http://www.sped.fazenda.gov.br/nfse"
XSD = Path(__file__).parent / "xsd"
IBSCBS = {"cIndOp": "100301", "CST": "000", "cClassTrib": "000001", "indFinal": "0"}


def _cfg(regime: dict[str, Any] | None = None, leiaute: str = "", **servico: Any) -> ClienteConfig:
    d = copy.deepcopy(CONFIG_VALIDA)
    d["prestador"]["regime"].update(regime or {})
    d["servico"].update(servico)
    if leiaute:
        d["leiaute"] = leiaute
    return ClienteConfig.from_dict(d)


def _sn(**servico: Any) -> ClienteConfig:
    """ME/EPP pronto para 2027: regApIBSCBSSN 1, cAtvSN 07, NBS e o grupo IBS/CBS."""
    base: dict[str, Any] = {"cAtvSN": "07", "cNBS": "123019800", "ibscbs": IBSCBS}
    return _cfg({"regApIBSCBSSN": 1}, **{**base, **servico})


def _montar(cfg: ClienteConfig, leiaute: str) -> str:
    return dps.montar_dps(cfg, numero="12", serie="70000", valor="1262.90",
                          descricao="Servico de teste", tomador=None, ambiente="producao",
                          dh_emi="2026-12-31T10:00:00-03:00", d_comp="2027-01-04",
                          leiaute=leiaute)


def _erros(xml: str, leiaute: str) -> list[str]:
    esquema = etree.XMLSchema(etree.parse(str(XSD / leiaute / "DPS_v1.01.xsd")))
    if esquema.validate(etree.fromstring(xml.encode())):
        return []
    return [e.message for e in esquema.error_log]


def _filhos(xml: str, caminho: str) -> list[str]:
    inf = etree.fromstring(xml.encode()).find(f"{{{NS}}}infDPS")
    el = inf.find("/".join(f"{{{NS}}}{p}" for p in caminho.split("/")))
    assert el is not None
    return [etree.QName(c).localname for c in el]


def _texto(xml: str, caminho: str) -> str:
    inf = etree.fromstring(xml.encode()).find(f"{{{NS}}}infDPS")
    el = inf.find("/".join(f"{{{NS}}}{p}" for p in caminho.split("/")))
    assert el is not None and el.text is not None
    return el.text


def _c14n(xml: str) -> bytes:
    inf = etree.fromstring(xml.encode()).find(f"{{{NS}}}infDPS")
    return etree.tostring(inf, method="c14n")


# ── Onde os campos entram ────────────────────────────────────────────────────────────────────

def test_os_dois_campos_nas_posicoes_do_anexo_vi():
    xml = _montar(_sn(), LEIAUTE_NT009_SN)
    assert _filhos(xml, "prest/regTrib") == [
        "opSimpNac", "regApTribSN", "regApIBSCBSSN", "regEspTrib"]
    assert _filhos(xml, "serv/cServ") == [
        "cTribNac", "cTribMun", "cNBS", "cAtvSN", "xDescServ"]
    assert _texto(xml, "prest/regTrib/regApIBSCBSSN") == "1"
    assert _texto(xml, "serv/cServ/cAtvSN") == "07"
    assert _erros(xml, LEIAUTE_NT009_SN) == []


def test_o_esquema_de_hoje_recusa_os_campos():
    """Controle negativo: sem o leiaute certo, a mesma DPS é E1235 — por isso só por config."""
    erros = _erros(_montar(_sn(), LEIAUTE_NT009_SN), LEIAUTE_NT009)
    assert any("regApIBSCBSSN" in e for e in erros)


@pytest.mark.parametrize("leiaute", [LEIAUTE_PRODUCAO, LEIAUTE_NT009])
def test_nos_leiautes_de_hoje_a_config_preparada_nao_muda_a_dps(leiaute):
    """A config pode chegar a 2027 antes do esquema: os campos ficam de fora, byte a byte."""
    sem = _cfg(cNBS="123019800", ibscbs=IBSCBS)
    com = _sn()
    assert _c14n(_montar(com, leiaute)) == _c14n(_montar(sem, leiaute))
    assert _erros(_montar(com, leiaute), leiaute) == []


def test_atividade_com_um_digito_sai_com_dois():
    assert atividade_sn("7") == "07"
    assert atividade_sn(9) == "09"
    assert atividade_sn("") == ""
    xml = _montar(_sn(cAtvSN="9"), LEIAUTE_NT009_SN)
    assert _texto(xml, "serv/cServ/cAtvSN") == "09"


def test_config_em_json_le_os_dois_campos():
    d = copy.deepcopy(CONFIG_VALIDA)
    d["prestador"]["regime"]["regApIBSCBSSN"] = 2
    d["servico"]["cAtvSN"] = "09"
    cfg = ClienteConfig.from_dict(d)
    assert (cfg.prestador.regime.regApIBSCBSSN, cfg.servico.cAtvSN) == (2, "09")
    assert cfg.validar() == []


# ── Obrigatórios no leiaute nt009-sn (RN 313 e 449) ──────────────────────────────────────────

def test_me_epp_sem_os_campos_nao_monta_no_leiaute_novo():
    with pytest.raises(ValueError, match="regApIBSCBSSN.*obrigatório"):
        _montar(_cfg(cAtvSN="07"), LEIAUTE_NT009_SN)
    with pytest.raises(ValueError, match="cAtvSN.*obrigatório"):
        _montar(_cfg({"regApIBSCBSSN": 1}), LEIAUTE_NT009_SN)


def test_validar_cobra_os_campos_quando_a_config_forca_o_leiaute():
    problemas = _cfg(leiaute=LEIAUTE_NT009_SN).validar()
    assert any("regApIBSCBSSN" in p and "obrigatório" in p for p in problemas)
    assert any("cAtvSN" in p and "obrigatório" in p for p in problemas)
    assert _cfg(leiaute=LEIAUTE_NT009).validar() == []          # nos outros, não cobra


def test_mei_e_nao_optante_seguem_sem_os_campos_no_leiaute_novo():
    mei = _cfg({"opSimpNac": 2}, tributos={"indTotTrib": 0})
    xml = _montar(mei, LEIAUTE_NT009_SN)
    assert "regApIBSCBSSN" not in _filhos(xml, "prest/regTrib")
    assert "cAtvSN" not in _filhos(xml, "serv/cServ")
    assert _erros(xml, LEIAUTE_NT009_SN) == []


# ── O que o validador recusa ─────────────────────────────────────────────────────────────────

def test_so_o_me_epp_informa():
    mei = _cfg({"opSimpNac": 2, "regApIBSCBSSN": 1}, tributos={"indTotTrib": 0}, cAtvSN="07")
    problemas = mei.validar()
    assert any("regApIBSCBSSN é só do ME/EPP" in p for p in problemas)
    assert any("cAtvSN é só do ME/EPP" in p for p in problemas)


@pytest.mark.parametrize("valor", [0, 4, "1"])
def test_regime_de_apuracao_fora_do_dominio(valor):
    assert any("regApIBSCBSSN deve ser" in p for p in _cfg({"regApIBSCBSSN": valor}).validar())


@pytest.mark.parametrize("valor", ["01", "06", "15", "91", "x"])
def test_atividade_fora_do_dominio_da_nfse(valor):
    assert any("cAtvSN deve ser um de" in p for p in _cfg(cAtvSN=valor).validar())


def test_dominio_da_atividade_e_o_da_nt():
    assert ATIVIDADES_SN_NFSE == ("07", "08", "09", "10", "11", "12", "13", "14", "90")


@pytest.mark.parametrize(("cTribNac", "cAtvSN", "ok"), [
    ("160101", "10", True),     # transporte municipal de passageiros: só 10
    ("160101", "07", False),
    ("990401", "11", True),     # locação de bens móveis e afins sem ISS: só 11
    ("990401", "07", False),
    ("070201", "12", True),     # construção civil 7.02 / 7.05: 12 (Anexo III) ou 13 (Anexo IV)
    ("070501", "13", True),
    ("070201", "14", False),
    ("171901", "10", False),    # e o código amarrado não vale fora do seu item
    ("171901", "12", False),
    ("171901", "09", True),
    ("041601", "07", True),
])
def test_atividade_amarrada_ao_item(cTribNac, cAtvSN, ok):
    problemas = [p for p in _cfg(cTribNac=cTribNac, cAtvSN=cAtvSN).validar() if "RN 451" in p]
    assert (problemas == []) is ok, problemas


# ── A dica quando o SEFIN ainda não tem os campos ────────────────────────────────────────────

def test_dica_quando_o_ambiente_ainda_nao_aplica_o_leiaute_novo():
    msg = "[E1235] Falha no esquema XML: elemento 'cAtvSN' não esperado"
    dica = _dica_leiaute(msg, "E1235", LEIAUTE_NT009_SN)
    assert dica is not None and dica.startswith("[E1235]")
    assert f'"leiaute": "{LEIAUTE_NT009}"' in dica
    assert _dica_leiaute(msg, "E1235", LEIAUTE_NT009) == msg      # sem o leiaute novo, sem dica
