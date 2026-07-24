"""CNPJ alfanumérico (NT Conjunta 2025.001) — validação + DPS.

Trava o comportamento novo: o motor aceita emitente/tomador com CNPJ alfanumérico
e NÃO apaga as letras ao montar/validar a DPS. Regressão numérica coberta pela
suíte existente (o golden byte-a-byte continua batendo com CNPJ numérico).
"""

from __future__ import annotations

from pynfsenacional import documentos


# Exemplo canônico da NT/RFB: 12.ABC.345/01DE-35 (DV 35, ASCII-48, mód-11).
CNPJ_ALFA = "12ABC34501DE35"


def test_norm_documento_preserva_letras():
    assert documentos.norm_documento("12.abc.345/01de-35") == CNPJ_ALFA


def test_cnpj_valido_alfanumerico():
    assert documentos.cnpj_valido(CNPJ_ALFA)
    assert documentos.cnpj_valido("12.ABC.345/01DE-35")


def test_dv_errado_rejeitado():
    assert not documentos.cnpj_valido("12ABC34501DE34")


def test_regressao_numerica():
    # CNPJ numérico real: DV inalterado (ASCII-48 == int para dígitos).
    assert documentos.cnpj_valido("23.629.677/0001-99")
    assert not documentos.cnpj_valido("11111111111111")


def test_cpf_intocado():
    assert documentos.cpf_valido("111.444.777-35")
    assert not documentos.cpf_valido("11111111111")


def test_dps_emite_cnpj_alfanumerico_do_prestador():
    from conftest import CONFIG_VALIDA
    from pynfsenacional import dps
    from pynfsenacional.config import ClienteConfig

    bruto = {**CONFIG_VALIDA}
    bruto["prestador"] = {**CONFIG_VALIDA["prestador"], "cnpj": CNPJ_ALFA}
    cfg = ClienteConfig.from_dict(bruto)
    xml = dps.montar_dps(
        cfg, numero="1", valor=10.0, descricao="Teste",
        tomador=None, ambiente="homologacao",
        dh_emi="2026-07-10T12:00:00-03:00", d_comp="2026-07-10",
    )
    assert "<CNPJ>12ABC34501DE35</CNPJ>" in xml  # letras preservadas no <prest> (14, com DV)
    assert 'Id="DPS3304557212ABC34501DE35' in xml  # inscrFed alfanumérico no Id da DPS
