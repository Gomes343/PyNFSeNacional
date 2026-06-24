"""Validação de CPF/CNPJ (dígito verificador mód-11) — stdlib pura.

Usado pela validação fiscal (`config.validar`, tomador da DPS). Isolado aqui para
ser testável de forma independente (inclusive property-based) e reutilizável.
"""

from __future__ import annotations

import re

_NAO_DIGITO = re.compile(r"\D")


def digitos(s: str | None) -> str:
    """Remove tudo que não for dígito (espelha `gt_digitos` do PHP)."""
    return _NAO_DIGITO.sub("", s or "")


def _mod11_dv(base: str, pesos: list[int]) -> int:
    """Dígito verificador mód-11 da Receita: resto<2 → 0, senão 11−resto."""
    soma = sum(int(d) * p for d, p in zip(base, pesos, strict=True))
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
    """True se `valor` (com ou sem máscara) é um CNPJ válido (14 díg + mód-11)."""
    cnpj = digitos(valor)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    dv1 = _mod11_dv(cnpj[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    dv2 = _mod11_dv(cnpj[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return cnpj[12] == str(dv1) and cnpj[13] == str(dv2)
