"""A chave de acesso da NFS-e (50 posições) e o que dá para tirar dela sem consultar ninguém.

Layout: cMun 7 · tpAmb 1 · tpInsc 1 · CNPJ/CPF 14 · **nNFSe 13** · AAMM 4 · código 9 · DV 1.
Conferido contra 325 NFS-e autorizadas: o número de dentro da chave casa com o `<nNFSe>` em
todas. Serve à nota recuperada (`ja_emitida`), que pode chegar só com a chave.
"""

from __future__ import annotations

import re

_RE_ID_INFNFSE = re.compile(r"<infNFSe\b[^>]*\bId=\"NFS([0-9A-Z]{50})\"")


def limpar(chave: str) -> str:
    """Tira o prefixo "NFS" e qualquer separador. Não valida o tamanho. Letras ficam: o
    CNPJ alfanumérico (NT 2025.001) entra na chave como está."""
    c = (chave or "").strip().upper()
    if c[:3] == "NFS":
        c = c[3:]
    return re.sub(r"[^0-9A-Z]", "", c)


def numero_da_chave(chave: str | None) -> str | None:
    """nNFSe de dentro da chave — ou None se ela não tiver 50 dígitos."""
    c = limpar(chave or "")
    if len(c) != 50 or not c[23:36].isdigit():
        return None
    return str(int(c[23:36]))


def chave_do_xml(xml: str | None) -> str | None:
    """A chave a partir do XML da NFS-e: o `Id` do `infNFSe` (`NFS` + 50 dígitos).

    O XML devolvido pela SEFIN não traz `<chNFSe>`; a chave mora nesse `Id`."""
    m = _RE_ID_INFNFSE.search(xml or "")
    return m.group(1) if m else None
