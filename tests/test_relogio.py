"""Relógio da DPS — a margem de segurança do E0008 e a trava de meia-noite.

O que estes testes seguram (incidente de 30/08/2026, em produção): `dhEmi` era o PISO do
segundo corrente, então a folga contra o relógio do SEFIN era a fração de segundo já
decorrida — 0 a 1s, sorteada. Com o pool do SEFIN espalhado até ~1s atrás do nosso,
1 nota em 16 caiu em E0008. A margem tem de existir e tem de ser VISÍVEL num teste;
"funcionou nas 15 outras" é exatamente o sintoma que deixou isso passar.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pynfsenacional import relogio
from pynfsenacional.relogio import FUSO_BRASILIA, MARGEM_E0008_S


def test_dh_emi_nasce_no_passado():
    """A regressão do E0008: sem argumento, `dhEmi` tem de vir ATRÁS do relógio real."""
    antes = datetime.now(FUSO_BRASILIA)
    emitido = datetime.fromisoformat(relogio.dh_emi())
    depois = datetime.now(FUSO_BRASILIA)

    assert emitido <= antes, "dhEmi não pode ser igual nem posterior ao agora (E0008)"
    # Recuo efetivo entre a margem cheia e a margem + 1s (o truncamento do segundo).
    assert timedelta(seconds=MARGEM_E0008_S) <= depois - emitido <= timedelta(
        seconds=MARGEM_E0008_S + 2
    )


def test_margem_nao_e_zero():
    """Trava explícita: alguém zerar a constante reabre o incidente em silêncio."""
    assert MARGEM_E0008_S >= 2


def test_momento_explicito_nao_leva_recuo():
    """O golden fixa `dh_emi` para o byte-diff — recuar aqui quebraria a assinatura."""
    fixo = datetime(2026, 6, 25, 10, 0, 0, tzinfo=FUSO_BRASILIA)
    assert relogio.dh_emi(fixo) == "2026-06-25T10:00:00-03:00"


def test_momento_naive_ganha_fuso_de_brasilia():
    assert relogio.dh_emi(datetime(2026, 6, 25, 10, 0, 0)).endswith("-03:00")


def test_dh_emi_sem_microssegundos():
    """Formato tem de seguir igual ao `date('c')` do PHP: segundos, sem fração."""
    assert "." not in relogio.dh_emi()
    assert relogio.dh_emi(datetime(2026, 6, 25, 10, 0, 0, 123456)) == "2026-06-25T10:00:00-03:00"


def test_recuar_longe_da_meia_noite():
    t = datetime(2026, 8, 30, 20, 23, 40, 50_000, tzinfo=FUSO_BRASILIA)
    assert relogio.recuar(t, 5) == datetime(2026, 8, 30, 20, 23, 35, tzinfo=FUSO_BRASILIA)


def test_recuar_trava_na_meia_noite():
    """00:00:02 do dia 1º NÃO pode virar 23:59:57 do mês anterior — trocaria a competência."""
    t = datetime(2026, 9, 1, 0, 0, 2, tzinfo=FUSO_BRASILIA)
    assert relogio.recuar(t, 5) == datetime(2026, 9, 1, 0, 0, 0, tzinfo=FUSO_BRASILIA)


def test_recuo_nunca_muda_o_dia():
    """Varre o dia inteiro, inclusive a borda: `dhEmi` e `dCompet` jamais discordam do DIA."""
    base = datetime(2026, 9, 1, tzinfo=FUSO_BRASILIA)
    instantes = [base + timedelta(seconds=s) for s in (0, 1, 2, 4, 5, 6, 30, 3600)]
    instantes.append(datetime(2026, 9, 1, 23, 59, 59, tzinfo=FUSO_BRASILIA))
    for t in instantes:
        assert relogio.recuar(t).date() == t.date(), f"recuo trocou o dia em {t}"


def test_dh_emi_e_d_comp_no_mesmo_dia():
    assert relogio.dh_emi()[:10] == relogio.d_comp()
