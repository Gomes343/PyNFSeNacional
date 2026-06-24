"""Relógio único do pacote — fuso **America/Sao_Paulo** (E0008).

Por que existe: o SEFIN roda no horário de Brasília; se `dhEmi` for gerado em UTC
(ou no fuso da máquina), a nota cai em **E0008** ("data de emissão posterior ao
processamento"). Toda data/hora fiscal da DPS passa por aqui.

Além de fixar o fuso, este módulo é o **ponto de injeção** de tempo: a montagem da
DPS aceita `dh_emi`/`d_comp` opcionais; quando ausentes, vêm daqui. Os testes e o
*golden harness* (byte-diff contra o PHP) passam valores FIXOS — sem isso `dhEmi`
varia a cada execução e `DigestValue`/`SignatureValue` nunca batem.

Formato de `dh_emi`: ISO 8601 com offset, igual ao `date('c')` da referência PHP
(ex.: ``2026-06-23T14:05:00-03:00`` — segundos, sem microssegundos).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

#: Fuso oficial do SEFIN Nacional (horário de Brasília).
FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")


def agora() -> datetime:
    """`datetime` *aware* no fuso de Brasília, sem microssegundos (como `date('c')`)."""
    return datetime.now(FUSO_BRASILIA).replace(microsecond=0)


def dh_emi(momento: datetime | None = None) -> str:
    """Formata `dhEmi` (ISO 8601 com offset). `momento=None` → agora em Brasília."""
    dt = momento or agora()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=FUSO_BRASILIA)
    return dt.replace(microsecond=0).isoformat()


def d_comp(momento: datetime | None = None) -> str:
    """Formata `dCompet` (`AAAA-MM-DD`). `momento=None` → hoje em Brasília."""
    dt = momento or agora()
    return dt.date().isoformat()
