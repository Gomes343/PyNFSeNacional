"""Geração local do DANFSe (PDF) a partir do XML da NFS-e. Lib: `BrazilFiscalReport`.

Necessário porque a API de PDF do governo (ADN) é descontinuada em 01/07/2026
(NT-008/2026) — ver docs/conhecimento-fiscal.md §1. Geramos o PDF localmente, a
partir do XML devolvido pelo SEFIN.

Os 2 gotchas do §6 (rótulo "SEM VALIDADE JURÍDICA" por `tpAmb` ≠ `ambGer`; UF do
local da prestação resolvida pelo IBGE) **já vêm corrigidos upstream** na
`BrazilFiscalReport` ≥ 1.0 — não precisamos repetir os patches da referência PHP.
"""

from __future__ import annotations

from pathlib import Path


def render(nfse_xml: str, destino: str | Path) -> str:
    """Gera o PDF do DANFSe a partir do XML da NFS-e; devolve o caminho do PDF.

    `nfse_xml`: o XML da NFS-e devolvido pelo SEFIN (não o da DPS).

    Requer o extra opcional: `pip install PyNFSeNacional[danfse]`.
    """
    try:
        from brazilfiscalreport.danfse import Danfse
    except ImportError as e:
        raise ImportError(
            "geração do DANFSe requer o extra opcional: pip install PyNFSeNacional[danfse]"
        ) from e

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    Danfse(xml=nfse_xml).output(str(destino))
    return str(destino)
