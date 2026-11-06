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

import re
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

# TSMotivo do XSD de eventos v1.01: minLength 15, maxLength 255. Até a 1.6.0 a lib parava em
# 200 (sem fonte); o XSD oficial aceita 255 — §16.
JUSTIFICATIVA_MIN, JUSTIFICATIVA_MAX = 15, 255


def limpar_autor(autor: str | None) -> str:
    """O CNPJ/CPF do autor sem máscara, MAIÚSCULO (letras do CNPJ alfanumérico ficam).

    ☠️ Não é a limpeza da chave de acesso: `chave.limpar` tira um "NFS" do começo, e um CNPJ
    alfanumérico que comece com NFS virava CPFAutor de 11 posições."""
    return re.sub(r"[^0-9A-Z]", "", (autor or "").upper())


def validar_cancelamento(chave: str, motivo: int, justificativa: str, modo: str,
                         autor: str | None = None) -> list[str]:
    """Os problemas que fazem a SEFIN recusar o pedido — checados antes de assinar.

    Com `autor` (o CNPJ/CPF de quem pede), confere também que a chave é de uma nota DELE: a
    chave traz o emitente (`chave.emitente_da_chave`), e um evento assinado pelo prestador
    errado não tem como dar certo. Sem `autor`, essa conferência não é feita."""
    problemas = []
    if len(_chave.limpar(chave)) != 50:
        problemas.append("chave de acesso deve ter 50 posições")
    elif autor is not None and _chave.chave_do_emitente(chave, limpar_autor(autor)) is False:
        problemas.append(
            f"a chave é de uma nota de outro emitente ({_chave.emitente_da_chave(chave)}), "
            f"não de {limpar_autor(autor)} — nada foi enviado")
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
    conferir_emitente: bool = True,
) -> str:
    """Monta o `pedRegEvento` de cancelamento (NÃO assinado).

    `autor`: CNPJ (14) ou CPF (11) de quem pede — o prestador. `dh_evento`/`ver_aplic`
    são injetáveis para teste determinístico. `conferir_emitente=False` desliga a recusa da
    chave de outro emitente (para quem pede por procuração, autor ≠ emitente).
    """
    problemas = validar_cancelamento(chave, motivo, justificativa, modo,
                                     autor=autor if conferir_emitente else None)
    if ambiente not in ("homologacao", "producao"):
        problemas.append(f"ambiente inválido: {ambiente!r}")
    doc = limpar_autor(autor)
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
