"""Validação de CPF/CNPJ (dígito verificador mód-11) — stdlib pura.

Usado pela validação fiscal (`config.validar`, tomador da DPS). Isolado aqui para
ser testável de forma independente (inclusive property-based) e reutilizável.

CNPJ ALFANUMÉRICO (NT Conjunta 2025.001, produção 06/07/2026): as 12 primeiras
posições do CNPJ passam a aceitar letras maiúsculas [A-Z0-9]; as 2 últimas (DV)
seguem numéricas. No cálculo do DV mód-11, cada caractere entra pelo valor
**ASCII - 48** (0→0…9→9, A→17…Z→42) — números têm o mesmo valor de sempre, então
o DV dos CNPJs numéricos atuais não muda (regressão zero). Exemplo da NT:
base "12ABC34501DE" → DV "35".
"""

from __future__ import annotations

import re

_NAO_DIGITO = re.compile(r"\D")
_NAO_ALNUM = re.compile(r"[^A-Z0-9]")
# CNPJ (numérico OU alfanumérico): 12 posições [A-Z0-9] + 2 dígitos de DV.
_RE_CNPJ = re.compile(r"^[A-Z0-9]{12}[0-9]{2}$")


def digitos(s: str | None) -> str:
    """Remove tudo que não for dígito.

    Usar SÓ para campos genuinamente numéricos (CEP, código de município, telefone,
    inscrição municipal, CPF). Para CNPJ use `norm_documento` — senão as letras do
    CNPJ alfanumérico seriam apagadas.
    """
    return _NAO_DIGITO.sub("", s or "")


def norm_documento(s: str | None) -> str:
    """Normaliza CNPJ/CPF preservando letras: MAIÚSCULO, só [A-Z0-9] (sem máscara).

    CPF (sempre numérico) sai igual a `digitos`. CNPJ alfanumérico mantém as letras
    das 12 primeiras posições. Não faz zfill (documento de nota já vem completo).
    """
    return _NAO_ALNUM.sub("", (s or "").upper())


def _valor_char(c: str) -> int:
    """Valor do caractere no DV mód-11: ASCII - 48 (dígito = ele mesmo; A=17…Z=42)."""
    return ord(c) - 48


def _mod11_dv(base: str, pesos: list[int]) -> int:
    """Dígito verificador mód-11 da Receita: resto<2 → 0, senão 11−resto.

    Usa o valor ASCII-48 de cada caractere (numérico e alfanumérico no mesmo cálculo).
    """
    soma = sum(_valor_char(d) * p for d, p in zip(base, pesos, strict=True))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def cpf_valido(valor: str | None) -> bool:
    """True se `valor` (com ou sem máscara) é um CPF válido (11 díg + mód-11)."""
    cpf = digitos(valor)
    if len(cpf) != 11 or cpf == cpf[0] * 11:  # rejeita repetidos (00000000000…)
        return False
    dv1 = _mod11_dv(cpf[:9], list(range(10, 1, -1)))
    dv2 = _mod11_dv(cpf[:10], list(range(11, 1, -1)))
    return cpf[9] == str(dv1) and cpf[10] == str(dv2)


def cnpj_valido(valor: str | None) -> bool:
    """True se `valor` é um CNPJ válido — numérico OU alfanumérico (NT 2025.001).

    Formato [A-Z0-9]{12}[0-9]{2} + DV mód-11 por ASCII-48. Rejeita repetidos.
    """
    cnpj = norm_documento(valor)
    if not _RE_CNPJ.match(cnpj) or cnpj == cnpj[0] * 14:
        return False
    dv1 = _mod11_dv(cnpj[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    dv2 = _mod11_dv(cnpj[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return cnpj[12] == str(dv1) and cnpj[13] == str(dv2)
