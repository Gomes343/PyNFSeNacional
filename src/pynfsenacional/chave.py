"""A chave de acesso da NFS-e (50 posições) e o que dá para tirar dela sem consultar ninguém.

Layout: cMun 7 · **ambGer 1** · tpInsc 1 · CNPJ/CPF 14 · **nNFSe 13** · AAMM 4 · código 9 · DV 1.
Conferido contra 325 NFS-e autorizadas: o número de dentro da chave casa com o `<nNFSe>` em
todas. Serve à nota recuperada (`ja_emitida`), que pode chegar só com a chave.

☠️ A 8ª posição é o **ambiente GERADOR** (1 = prefeitura, 2 = Sistema Nacional), não o tipo de
ambiente (produção/homologação): toda nota do Sistema Nacional tem 2 ali. A chave não diz em
que ambiente a nota foi emitida.

A 9ª posição é o tipo da inscrição do emitente (1 = CPF, 2 = CNPJ) e as 14 seguintes, a
inscrição (o CPF completado com zeros à esquerda): `emitente_da_chave` a devolve, para conferir
— antes de assinar um evento — que a nota é mesmo do prestador.
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


def emitente_da_chave(chave: str | None) -> str | None:
    """O CNPJ (14) ou o CPF (11) do EMITENTE da nota, tirado da chave — ou None se a chave não
    tiver 50 posições ou o tipo de inscrição (9ª posição) não for 1 (CPF) nem 2 (CNPJ).

    Serve para recusar, sem enviar nada, um evento de uma chave que é de OUTRO prestador
    (ex.: chave colada errada). Não confere o dígito verificador da chave."""
    c = limpar(chave or "")
    if len(c) != 50:
        return None
    tp, doc = c[8], c[9:23]
    if tp == "2":
        return doc
    if tp == "1" and doc.isdigit():
        return doc[-11:] if doc[:3] == "000" else None
    return None


def chave_do_emitente(chave: str | None, documento: str | None) -> bool | None:
    """A chave é de uma nota emitida por `documento` (CNPJ/CPF, com ou sem máscara)? None se
    não der para saber (chave fora do layout ou documento vazio)."""
    emit = emitente_da_chave(chave)
    doc = re.sub(r"[^0-9A-Z]", "", (documento or "").upper())
    if emit is None or not doc:
        return None
    return emit == doc
