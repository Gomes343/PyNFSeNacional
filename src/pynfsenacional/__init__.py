"""PyNFSeNacional — Emissão de NFS-e pela API SEFIN Nacional (DPS) + DANFSe local.

API pública:
    from pynfsenacional import Emissor
    emissor = Emissor("config/cliente.json")
    nota = emissor.emitir(valor=Decimal("150.00"), descricao="...", tomador={...})
    nota.danfse("nota.pdf")
    emissor.consultar(chave)                       # a nota (e o XML) pela chave
    emissor.consultar_convenio()                   # o município emite pelo Nacional?
    emissor.consultar_aliquota("07.11.01.000")     # alíquotas do serviço no município
    emissor.cancelar(chave, justificativa="...")   # e101101 (ou modo="analise", e101103)
    emissor.sincronizar_dfe(nsu)                   # caixa postal DF-e do CNPJ

Estado: lançado (1.x), em produção real. Ver docs/roadmap.md para o escopo e
docs/conhecimento-fiscal.md para a regra fiscal (DPS, E-codes, numeração, DANFSe).
"""

from __future__ import annotations

from .config import ClienteConfig, ConfigError
from .dfe import DocumentoDfe, RespostaDfe
from .emissor import Emissor, Nota, ResultadoEvento

#: Fonte única da versão (o pyproject a lê daqui, por `[tool.hatch.version]`). Até a 1.6.0 ela
#: vinha do metadado instalado — e uma instalação EDITÁVEL feita na 1.0.0 seguia dizendo 1.0.0
#: enquanto rodava o código novo.
__version__ = "1.7.0"

__all__ = ["Emissor", "Nota", "ResultadoEvento", "ClienteConfig", "ConfigError",
           "DocumentoDfe", "RespostaDfe", "__version__"]
