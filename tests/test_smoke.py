"""Smoke tests — o básico que sempre tem de funcionar: importar o pacote, carregar a
config em dataclasses, validar e construir o Emissor. A emissão ponta-a-ponta (com o
SEFIN mockado) está em test_emissor.py; o transporte isolado em test_sefin.py.
"""

import pytest
from conftest import CONFIG_VALIDA

import pynfsenacional
from pynfsenacional import ClienteConfig, Emissor


def test_pacote_importavel():
    assert pynfsenacional.__version__


def test_config_carrega_em_dataclasses():
    cfg = ClienteConfig.from_dict(CONFIG_VALIDA)
    assert cfg.id == "exemplo"
    assert cfg.prestador.cnpj == "11222333000181"
    assert cfg.prestador.regime.opSimpNac == 3        # Simples
    assert cfg.servico.cTribNac == "041601"           # 6 dígitos
    assert len(cfg.servico.cTribNac) == 6


def test_config_valida_sem_problemas():
    """A config fictícia de referência é fiscalmente válida (validar() vazio)."""
    assert ClienteConfig.from_dict(CONFIG_VALIDA).validar() == []


def test_emissor_constroi_de_config():
    cfg = ClienteConfig.from_dict(CONFIG_VALIDA)
    emissor = Emissor(cfg)
    assert emissor.ambiente == "homologacao"


def test_validacao_barra_emissao(pfx_teste, tmp_path):
    """O portão de validação roda no emitir(): config inválida nem chega ao transporte."""
    from pynfsenacional.config import ConfigError

    caminho, senha = pfx_teste
    cfg = ClienteConfig.from_dict({**CONFIG_VALIDA,
                                   "certificado": {"path": str(caminho), "senha": senha},
                                   "servico": {**CONFIG_VALIDA["servico"], "cTribNac": "999"}})
    with pytest.raises(ConfigError, match="E1235"):
        Emissor(cfg, out_dir=tmp_path).emitir(valor=150.0, descricao="x")
