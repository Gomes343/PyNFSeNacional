"""Fase 7: CLI (cli.py) — roteamento de saída com o Emissor mockado."""

from __future__ import annotations

import pytest

from pynfsenacional import cli
from pynfsenacional.config import ConfigError
from pynfsenacional.emissor import Nota


def _fake_emissor(nota=None, exc=None):
    class FE:
        def __init__(self, *a, **k):
            pass

        def emitir(self, **k):
            if exc:
                raise exc
            return nota
    return FE


def test_cli_sucesso(monkeypatch, capsys):
    nota = Nota(status="ok", emitida=True, id_cliente="x", numero_nfse="147",
                chave_acesso="33ABC", nfse_xml="<NFSe/>")
    monkeypatch.setattr(cli, "Emissor", _fake_emissor(nota))
    rc = cli.main(["emitir", "cfg.json", "--valor", "150,00", "--descricao", "Serviço"])
    assert rc == 0
    assert "147" in capsys.readouterr().out


def test_cli_xml_out(monkeypatch, capsys, tmp_path):
    nota = Nota(status="ok", emitida=True, id_cliente="x", numero_nfse="9",
                chave_acesso="33", nfse_xml="<NFSe>ok</NFSe>")
    monkeypatch.setattr(cli, "Emissor", _fake_emissor(nota))
    saida = tmp_path / "nota.xml"
    rc = cli.main(["emitir", "cfg.json", "--valor", "1", "--descricao", "x",
                   "--xml-out", str(saida)])
    assert rc == 0
    assert saida.read_text() == "<NFSe>ok</NFSe>"


def test_cli_erro_retorna_1(monkeypatch, capsys):
    nota = Nota(status="erro", emitida=False, id_cliente="x", erro_msg="[E0312] xpto")
    monkeypatch.setattr(cli, "Emissor", _fake_emissor(nota))
    rc = cli.main(["emitir", "cfg.json", "--valor", "1", "--descricao", "x"])
    assert rc == 1
    assert "E0312" in capsys.readouterr().err


def test_cli_config_invalida_retorna_2(monkeypatch, capsys):
    monkeypatch.setattr(cli, "Emissor", _fake_emissor(exc=ConfigError("E1235: cTribNac")))
    rc = cli.main(["emitir", "cfg.json", "--valor", "1", "--descricao", "x"])
    assert rc == 2
    assert "config inválida" in capsys.readouterr().err


def test_cli_verbose_liga_log(monkeypatch):
    nota = Nota(status="ok", emitida=True, id_cliente="x", numero_nfse="1", chave_acesso="33")
    monkeypatch.setattr(cli, "Emissor", _fake_emissor(nota))
    assert cli.main(["-v", "emitir", "cfg.json", "--valor", "1", "--descricao", "x"]) == 0


def test_cli_sem_subcomando_erra():
    with pytest.raises(SystemExit):
        cli.main([])
