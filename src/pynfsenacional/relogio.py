"""Relógio único do pacote — fuso **America/Sao_Paulo** e margem de segurança (E0008).

Por que existe: o SEFIN roda no horário de Brasília; se `dhEmi` for gerado em UTC
(ou no fuso da máquina), a nota cai em **E0008** ("data de emissão posterior ao
processamento"). Toda data/hora fiscal da DPS passa por aqui.

⚠️ **E0008 tem uma SEGUNDA causa, e ela não é o fuso** (achada em 30/08/2026, em
produção). Fixar o fuso resolve o erro grosseiro de 3 horas, mas deixa a margem em ZERO:
`dhEmi` era o PISO do segundo corrente (`.replace(microsecond=0)`), então a única folga
era a fração de segundo já decorrida — entre 0 e 1s, sorteada a cada nota. Prova, nos
XMLs devolvidos pelo SEFIN nas 16 notas daquela noite: em **12 delas o `dhProc` caiu no
MESMO segundo do `dhEmi`**, e nas outras 4 apenas +1s. Estávamos sempre na fronteira.

E o relógio do SEFIN não é o nosso: medindo o header `Date` do IIS deles, o pool de
front-end aparece espalhado de ~0 a ~1s ATRÁS de nós. Quando a DPS é montada logo depois
da virada do segundo e cai num backend uns décimos atrasado, `dhEmi` fica no futuro DELES
→ E0008. É corrida, não erro determinístico: naquela noite bateu em 1 de 16 notas (~6%),
e a nota seguia perfeita — bastou o cliente reenviar. Por isso `dhEmi` agora nasce
**recuado de `MARGEM_E0008_S`**, em vez de depender da sorte do truncamento.

Além disso, este módulo é o **ponto de injeção** de tempo: a montagem da DPS aceita
`dh_emi`/`d_comp` opcionais; quando ausentes, vêm daqui. Os testes e o *golden harness*
(byte-diff contra o PHP) passam valores FIXOS — sem isso `dhEmi` varia a cada execução e
`DigestValue`/`SignatureValue` nunca batem. Um `momento` explícito é respeitado
LITERALMENTE, sem recuo, justamente para o golden continuar determinístico.

Formato de `dh_emi`: ISO 8601 com offset, igual ao `date('c')` da referência PHP
(ex.: ``2026-06-23T14:05:00-03:00`` — segundos, sem microssegundos).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

#: Fuso oficial do SEFIN Nacional (horário de Brasília).
FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")

#: Segundos de recuo do `dhEmi` para não empatar com o relógio do SEFIN (E0008).
#: 5s cobre com folga o espalhamento medido no pool deles (~0 a ~1s) e é fiscalmente
#: irrelevante — a competência é MENSAL e o minuto sequer aparece na DANFSe.
MARGEM_E0008_S = 5


def agora() -> datetime:
    """`datetime` *aware* no fuso de Brasília, sem microssegundos (como `date('c')`).

    É o "agora" honesto, SEM recuo — quem precisa da margem do E0008 é o `dh_emi`.
    """
    return datetime.now(FUSO_BRASILIA).replace(microsecond=0)


def recuar(momento: datetime, segundos: int = MARGEM_E0008_S) -> datetime:
    """Recua `momento` de `segundos` (truncando microssegundos) **sem cair no dia anterior**.

    A trava de meia-noite não é preciosismo: `dCompet` sai do mesmo dia que `dhEmi`, e
    recuar 5s às 00:00:02 do dia 1º jogaria a nota para o último dia do mês ANTERIOR —
    trocaria a COMPETÊNCIA (erro fiscal, que ninguém vê) para evitar um E0008 (que é só
    reenviar). Nesses poucos segundos por dia preferimos o risco antigo: `dhEmi` volta a
    ser 00:00:00, com margem zero.
    """
    recuado = (momento - timedelta(seconds=segundos)).replace(microsecond=0)
    meia_noite = momento.replace(hour=0, minute=0, second=0, microsecond=0)
    return max(recuado, meia_noite)


def dh_emi(momento: datetime | None = None) -> str:
    """Formata `dhEmi` (ISO 8601 com offset).

    `momento=None` → agora em Brasília **recuado de `MARGEM_E0008_S`**. Um `momento`
    explícito é usado LITERALMENTE (sem recuo): é assim que o golden fixa o valor.
    """
    if momento is None:
        return recuar(datetime.now(FUSO_BRASILIA)).isoformat()
    dt = momento if momento.tzinfo else momento.replace(tzinfo=FUSO_BRASILIA)
    return dt.replace(microsecond=0).isoformat()


def d_comp(momento: datetime | None = None) -> str:
    """Formata `dCompet` (`AAAA-MM-DD`). `momento=None` → hoje em Brasília.

    NÃO leva o recuo do `dh_emi`: a trava de meia-noite do `recuar()` garante que os dois
    nunca discordem do DIA, então a competência sai sempre do dia corrente.
    """
    dt = momento or agora()
    return dt.date().isoformat()
