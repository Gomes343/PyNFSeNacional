"""Validação fiscal (Fase 2): um teste por E-code (caso bom × caso ruim),
loader tolerante, e property-based para CPF/CNPJ (mód-11) e o parser pt-BR da CLI.
"""

from __future__ import annotations

import copy

import pytest
from conftest import CONFIG_VALIDA
from hypothesis import given
from hypothesis import strategies as st

from pynfsenacional import documentos
from pynfsenacional.cli import _to_float
from pynfsenacional.config import ClienteConfig, ConfigError, validar_tomador


def _cfg(**mutacoes):
    """Config válida com mutações pontuais em blocos aninhados (ex.: servico__cTribNac)."""
    d = copy.deepcopy(CONFIG_VALIDA)
    for chave, valor in mutacoes.items():
        if "__" in chave:
            bloco, campo = chave.split("__", 1)
            d[bloco][campo] = valor
        else:
            d[chave] = valor
    return ClienteConfig.from_dict(d)


# ── validar() — um problema por E-code ──────────────────────────────────────
def test_config_valida_nao_tem_problemas():
    assert _cfg().validar() == []


@pytest.mark.parametrize(
    "mutacao, agulha",
    [
        ({"prestador__cnpj": "12345678000100"}, "CNPJ do prestador inválido"),
        ({"prestador__codigo_municipio": "33045"}, "7 dígitos"),
        ({"servico__cTribNac": "0416010"}, "E1235"),          # 7 dígitos
        ({"servico__cTribNac": "04160"}, "E1235"),            # 5 dígitos
        ({"servico__cTribMun": ""}, "E0312"),                 # sem desdobro municipal
        ({"servico__codigo_municipio_prestacao": "abc"}, "local da prestação"),
        ({"ambiente": "producaoXX"}, "ambiente inválido"),
    ],
)
def test_validar_pega_ecode(mutacao, agulha):
    problemas = _cfg(**mutacao).validar()
    assert any(agulha in p for p in problemas), (mutacao, problemas)


def test_simples_exige_ptottribsn():
    # opSimpNac=3 (ME/EPP) sem pTotTribSN → E0712/E1235
    d = copy.deepcopy(CONFIG_VALIDA)
    d["servico"]["tributos"] = {}
    problemas = ClienteConfig.from_dict(d).validar()
    assert any("E0712" in p for p in problemas), problemas


def test_nao_optante_nao_exige_ptottribsn():
    # opSimpNac=1 (Não Optante) não usa pTotTribSN → sem esse problema
    d = copy.deepcopy(CONFIG_VALIDA)
    d["prestador"]["regime"]["opSimpNac"] = 1
    d["servico"]["tributos"] = {}
    problemas = ClienteConfig.from_dict(d).validar()
    assert not any("pTotTribSN" in p for p in problemas), problemas


# ── validar_tomador() — E1235 §7 ────────────────────────────────────────────
def test_tomador_none_ou_sem_doc_ok():
    assert validar_tomador(None) == []
    assert validar_tomador({}) == []
    assert validar_tomador({"nome": "Sem doc"}) == []  # consumidor final → omite <toma>


def test_tomador_com_doc_exige_nome():
    problemas = validar_tomador({"cpf_cnpj": "11144477735"})
    assert any("xNome" in p or "nome" in p for p in problemas)


def test_tomador_doc_invalido():
    assert any("CPF" in p for p in validar_tomador({"cpf_cnpj": "11111111111", "nome": "X"}))
    assert any("CNPJ" in p for p in validar_tomador({"cpf_cnpj": "11111111111111", "nome": "X"}))


def test_tomador_valido_sem_problemas():
    assert validar_tomador({"cpf_cnpj": "111.444.777-35", "nome": "Fulano"}) == []


# ── loader tolerante (erro de schema amigável) ──────────────────────────────
def test_bloco_ausente_da_configerror():
    d = copy.deepcopy(CONFIG_VALIDA)
    del d["servico"]
    with pytest.raises(ConfigError, match="servico"):
        ClienteConfig.from_dict(d)


def test_campo_desconhecido_da_configerror():
    d = copy.deepcopy(CONFIG_VALIDA)
    d["certificado"]["caminho"] = "x"  # deveria ser 'path'
    with pytest.raises(ConfigError, match="não reconhecido"):
        ClienteConfig.from_dict(d)


def test_json_com_comentarios_da_configerror(tmp_path):
    p = tmp_path / "c.jsonc"
    p.write_text('{\n  // comentário\n  "id": "x"\n}', encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON"):
        ClienteConfig.from_json(p)


# ── property-based: documentos (mód-11) ─────────────────────────────────────
@given(st.integers(min_value=0, max_value=9))
def test_repetidos_nunca_validos(d):
    assert not documentos.cnpj_valido(str(d) * 14)
    assert not documentos.cpf_valido(str(d) * 11)


@given(st.text(alphabet="0123456789.-/ ", max_size=20))
def test_mascara_nao_muda_validade(s):
    # inserir pontuação/espaço não pode mudar o veredito (só dígitos contam)
    assert documentos.cnpj_valido(s) == documentos.cnpj_valido(documentos.digitos(s))
    assert documentos.cpf_valido(s) == documentos.cpf_valido(documentos.digitos(s))


# ── property-based: _to_float (pt-BR) ───────────────────────────────────────
@pytest.mark.parametrize(
    "txt, esperado",
    [("1.262,90", 1262.90), ("1262.90", 1262.90), ("100", 100.0), ("0,00", 0.0),
     ("1.000.000,01", 1000000.01)],
)
def test_to_float_ptbr(txt, esperado):
    assert _to_float(txt) == pytest.approx(esperado)


@given(st.integers(min_value=0, max_value=99_999_999))
def test_to_float_milhar_ptbr_roundtrip(centavos):
    valor = centavos / 100
    # formata com separador de milhar pt-BR ("1.234,56") e confere o round-trip
    txt = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    assert _to_float(txt) == pytest.approx(valor)
