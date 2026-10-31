"""Eventos da NFS-e — cancelamento direto (e101101) e análise fiscal (e101103).

Dois cancelamentos, conforme o município (docs/conhecimento-fiscal.md §16):
  • `direto`  → e101101, cancelamento imediato pelo contribuinte.
  • `analise` → e101103, Solicitação de Análise Fiscal para Cancelamento. É o único aceito
    onde o município não deixa cancelar direto (o direto volta E0823); a nota fica "em
    análise" até o fisco municipal deferir.

O pedido (`pedRegEvento`) é assinado no `infPedReg` com o mesmo perfil da DPS e vai ao
`POST /nfse/{chave}/eventos`. ☠️ O `xDesc` é uma enumeração do XSD e a SEFIN exige o texto
ACENTUADO, embora o XSD publicado o liste sem acento — sem acento volta E1235.
"""

from __future__ import annotations

from datetime import datetime

from lxml import etree

from . import chave as _chave
from . import relogio
from .config import ConfigError
from .dps import NS, VER_APLIC, _el

MODOS = {
    "direto": ("101101", "Cancelamento de NFS-e"),
    "analise": ("101103", "Solicitação de Análise Fiscal para Cancelamento de NFS-e"),
}

MOTIVOS = {1: "Erro na Emissão", 2: "Serviço não Prestado", 9: "Outros"}

JUSTIFICATIVA_MIN, JUSTIFICATIVA_MAX = 15, 200


def validar_cancelamento(chave: str, motivo: int, justificativa: str, modo: str) -> list[str]:
    """Os problemas que fazem a SEFIN recusar o pedido — checados antes de assinar."""
    problemas = []
    if len(_chave.limpar(chave)) != 50:
        problemas.append("chave de acesso deve ter 50 posições")
    if motivo not in MOTIVOS:
        problemas.append(f"motivo inválido: {motivo!r} (1=Erro na Emissão, "
                         "2=Serviço não Prestado, 9=Outros)")
    tam = len((justificativa or "").strip())
    if not JUSTIFICATIVA_MIN <= tam <= JUSTIFICATIVA_MAX:
        problemas.append(f"justificativa deve ter entre {JUSTIFICATIVA_MIN} e "
                         f"{JUSTIFICATIVA_MAX} caracteres (tem {tam})")
    if modo not in MODOS:
        problemas.append(f"modo inválido: {modo!r} (use 'direto' ou 'analise')")
    return problemas


def montar_cancelamento(
    *, chave: str, autor: str, motivo: int, justificativa: str, ambiente: str,
    modo: str = "direto", dh_evento: datetime | None = None, ver_aplic: str | None = None,
) -> str:
    """Monta o `pedRegEvento` de cancelamento (NÃO assinado).

    `autor`: CNPJ (14) ou CPF (11) de quem pede — o prestador. `dh_evento`/`ver_aplic`
    são injetáveis para teste determinístico.
    """
    problemas = validar_cancelamento(chave, motivo, justificativa, modo)
    if ambiente not in ("homologacao", "producao"):
        problemas.append(f"ambiente inválido: {ambiente!r}")
    doc = _chave.limpar(autor)
    if len(doc) not in (11, 14):
        problemas.append("autor deve ser um CNPJ (14) ou CPF (11)")
    if problemas:
        raise ConfigError("pedido de cancelamento inválido:\n  - " + "\n  - ".join(problemas))

    ch = _chave.limpar(chave)
    tipo, x_desc = MODOS[modo]
    momento = dh_evento or relogio.recuar(relogio.agora())

    raiz = etree.Element(f"{{{NS}}}pedRegEvento", nsmap={None: NS}, versao="1.01")
    inf = _el(raiz, "infPedReg")
    inf.set("Id", f"PRE{ch}{tipo}")
    _el(inf, "tpAmb", "1" if ambiente == "producao" else "2")
    _el(inf, "verAplic", ver_aplic or VER_APLIC)
    _el(inf, "dhEvento", relogio.dh_emi(momento))
    _el(inf, "CNPJAutor" if len(doc) == 14 else "CPFAutor", doc)
    _el(inf, "chNFSe", ch)
    ev = _el(inf, f"e{tipo}")
    _el(ev, "xDesc", x_desc)
    _el(ev, "cMotivo", str(motivo))
    _el(ev, "xMotivo", justificativa.strip())
    return str(etree.tostring(raiz, encoding="unicode"))
