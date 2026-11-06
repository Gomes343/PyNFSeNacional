"""O pacote em si: versão, pisos de dependência, sdist e a sintaxe do Python 3.10."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

import pynfsenacional

RAIZ = Path(__file__).resolve().parent.parent

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10
    tomllib = None


def _pyproject():
    if tomllib is None:
        pytest.skip("tomllib só no 3.11+")
    return tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))


def test_versao_vem_do_codigo_e_tem_changelog():
    """A versão é uma constante do código (o pyproject a lê de lá): uma instalação editável
    antiga não pode dizer uma versão e rodar outra."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", pynfsenacional.__version__)
    proj = _pyproject()["project"]
    assert "version" not in proj and "version" in proj["dynamic"]
    assert f"## [{pynfsenacional.__version__}]" in (RAIZ / "CHANGELOG.md").read_text(
        encoding="utf-8")


def _pisos():
    pisos = {}
    for dep in _pyproject()["project"]["dependencies"]:
        m = re.match(r"([A-Za-z0-9_.\-]+)\s*>=\s*([0-9.]+)", dep)
        if m:
            pisos[m.group(1).lower()] = m.group(2)
    return pisos


def test_celula_minimas_instala_os_pisos_declarados():
    minimas = {}
    for linha in (RAIZ / ".github" / "minimas.txt").read_text(encoding="utf-8").splitlines():
        linha = linha.split("#")[0].strip()
        if linha:
            nome, versao = linha.split("==")
            minimas[nome.strip().lower()] = versao.strip()
    pisos = _pisos()
    assert set(pisos) == set(minimas)
    for nome, piso in pisos.items():
        assert tuple(map(int, minimas[nome].split("."))) >= tuple(map(int, piso.split("."))), nome


def test_pisos_que_assinam():
    """Abaixo destes pisos o resolvedor montava signxml 3 + pyOpenSSL novo: não assinava."""
    p = _pisos()
    assert p["signxml"] == "4" and p["cryptography"] >= "43" and p["lxml"] >= "5.2.1"


def test_tzdata_no_windows():
    deps = _pyproject()["project"]["dependencies"]
    assert any(d.replace(" ", "").startswith("tzdata;sys_platform=='win32'") for d in deps)


def test_sdist_so_com_o_pacote():
    sdist = _pyproject()["tool"]["hatch"]["build"]["targets"]["sdist"]
    incluido = sdist["only-include"]
    assert "src/pynfsenacional" in incluido
    assert not any(p.startswith(("tests", "docs", ".github", "CLAUDE")) for p in incluido)


@pytest.mark.parametrize("arquivo", sorted((RAIZ / "src" / "pynfsenacional").glob("*.py")),
                         ids=lambda p: p.name)
def test_sintaxe_do_python_310(arquivo):
    ast.parse(arquivo.read_text(encoding="utf-8"), feature_version=(3, 10))
