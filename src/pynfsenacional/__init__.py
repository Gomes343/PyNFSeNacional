"""PyNFSeNacional — Emissão de NFS-e pela API SEFIN Nacional (DPS) + DANFSe local.

API pública:
    from pynfsenacional import Emissor
    emissor = Emissor("config/cliente.json")
    nota = emissor.emitir(valor=Decimal("150.00"), descricao="...", tomador={...})
    nota.danfse("nota.pdf")
    emissor.consultar(chave)                       # a nota (e o XML) pela chave
    emissor.cancelar(chave, justificativa="...")   # e101101 (ou modo="analise", e101103)
    emissor.sincronizar_dfe(nsu)                   # caixa postal DF-e do CNPJ

Estado: lançado (1.x), em produção real. Ver docs/roadmap.md para o escopo e
docs/conhecimento-fiscal.md para a regra fiscal (DPS, E-codes, numeração, DANFSe).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .config import ClienteConfig, ConfigError
from .dfe import DocumentoDfe, RespostaDfe
from .emissor import Emissor, Nota, ResultadoEvento

try:
    # Fonte única da versão: o metadado do pacote instalado (pyproject.toml).
    __version__ = version("PyNFSeNacionalGT")
except PackageNotFoundError:  # pragma: no cover - rodando do source, sem instalar
    __version__ = "0.0.0+unknown"

__all__ = ["Emissor", "Nota", "ResultadoEvento", "ClienteConfig", "ConfigError",
           "DocumentoDfe", "RespostaDfe", "__version__"]
