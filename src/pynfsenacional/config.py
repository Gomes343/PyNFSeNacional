"""Configuração do cliente/prestador — carrega o JSON descrito em
docs/conhecimento-fiscal.md §3 em dataclasses tipadas.

Duas responsabilidades:
  • **Carregar/representar** o JSON em dataclasses (`from_dict`/`from_json`), com erro
    de schema amigável (`ConfigError`) em vez de `TypeError` cru.
  • **Validar fiscalmente** (`validar`) — os E-codes que dão para pegar ANTES de tocar o
    SEFIN (cTribNac 6 díg, cTribMun presente, pTotTribSN se Simples, CNPJ/CPF mód-11…).
A montagem do XML da DPS fica em dps.py.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import documentos

_AMBIENTES = ("homologacao", "producao")


class ConfigError(ValueError):
    """Config malformada (bloco ausente, campo desconhecido, tipo errado)."""


def _construir(tipo: type, dados: dict[str, Any], contexto: str,
               ignorar: tuple[str, ...] = ()) -> Any:
    """Constrói uma dataclass a partir de um dict, com erro de schema amigável.

    Campos em `ignorar` são descartados (ex.: endereço/nome do prestador, que não
    são enviados — E0128/E0121). Chave desconhecida ou faltando → `ConfigError` com
    contexto, em vez do `TypeError` cru do `**splat`.
    """
    if not isinstance(dados, dict):
        raise ConfigError(f"{contexto}: esperado objeto JSON, recebido {type(dados).__name__}")
    dados = {k: v for k, v in dados.items() if k not in ignorar}
    campos = {f.name for f in dataclasses.fields(tipo)}
    desconhecidos = set(dados) - campos
    if desconhecidos:
        raise ConfigError(
            f"{contexto}: campo(s) não reconhecido(s): {sorted(desconhecidos)}. "
            f"Válidos: {sorted(campos)}"
        )
    try:
        return tipo(**dados)
    except TypeError as e:  # campo obrigatório ausente
        raise ConfigError(f"{contexto}: {e}") from e


@dataclass
class Certificado:
    """Certificado A1 ICP-Brasil do PRÓPRIO prestador (.pfx). NUNCA versionar."""
    path: str
    senha: str


@dataclass
class Regime:
    """Regime tributário do prestador (ver §3)."""
    opSimpNac: int          # 1=Não Optante · 2=MEI · 3=Optante ME/EPP (Simples)
    regApTribSN: int = 1    # apuração do SN (se optante)
    regEspTrib: int = 0     # regime especial (0=Nenhum)


@dataclass
class Prestador:
    cnpj: str               # 14 dígitos
    codigo_municipio: str   # IBGE 7 díg do emitente
    regime: Regime
    uf: str | None = None
    inscricao_municipal: str | None = None
    # Nome/endereço do prestador NÃO são enviados quando ele é o emitente (E0128/E0121).


@dataclass
class Servico:
    codigo_municipio_prestacao: str   # IBGE do local da prestação
    cTribNac: str                     # 6 dígitos (LC116)
    cTribMun: str                     # desdobro municipal
    descricao_padrao: str = "Serviço Prestado"
    tributos: dict[str, Any] = field(default_factory=dict)  # ex.: {"pTotTribSN": "6.00"}


@dataclass
class ClienteConfig:
    id: str
    nome_cliente: str
    certificado: Certificado
    prestador: Prestador
    servico: Servico
    ambiente: str = "homologacao"
    dados_nota: dict[str, Any] = field(default_factory=dict)

    # ── carregamento ──────────────────────────────────────────────────────────
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClienteConfig:
        if not isinstance(d, dict):
            raise ConfigError(f"config: esperado objeto JSON, recebido {type(d).__name__}")
        for chave in ("id", "nome_cliente", "certificado", "prestador", "servico"):
            if chave not in d:
                raise ConfigError(f"config: bloco/campo obrigatório ausente: '{chave}'")

        cert = _construir(Certificado, d["certificado"], "certificado")
        prest_raw = dict(d["prestador"])
        if "regime" not in prest_raw:
            raise ConfigError("prestador: bloco 'regime' obrigatório ausente")
        regime = _construir(Regime, prest_raw.pop("regime"), "prestador.regime")
        # endereço/telefone/email do prestador NÃO vão na DPS (E0128/E0121): descartados.
        prestador = _construir(
            Prestador, {**prest_raw, "regime": regime}, "prestador",
            ignorar=("endereco", "telefone", "email"),
        )
        servico = _construir(Servico, d["servico"], "servico")
        return cls(
            id=str(d["id"]),
            nome_cliente=d["nome_cliente"],
            certificado=cert,
            prestador=prestador,
            servico=servico,
            ambiente=d.get("ambiente", "homologacao"),
            dados_nota=d.get("dados_nota", {}),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> ClienteConfig:
        raw = Path(path).read_text(encoding="utf-8")
        try:
            dados = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"{path}: JSON inválido ({e}). O config real é JSON puro — comentários "
                f"// só existem no exemplo anotado .jsonc, não num config carregável."
            ) from e
        return cls.from_dict(dados)

    # ── validação fiscal ──────────────────────────────────────────────────────
    def validar(self) -> list[str]:
        """Lista os problemas fiscais (vazia = ok). Pega, ANTES do SEFIN, os E-codes
        que são determinísticos a partir da config. Ver docs/conhecimento-fiscal.md §4.
        """
        problemas: list[str] = []
        p, s, r = self.prestador, self.servico, self.prestador.regime

        # Prestador (emitente)
        if not documentos.cnpj_valido(p.cnpj):
            problemas.append(
                f"CNPJ do prestador inválido (14 dígitos + dígito verificador): {p.cnpj!r}"
            )
        if not (p.codigo_municipio.isdigit() and len(p.codigo_municipio) == 7):
            problemas.append(
                f"código IBGE do município do prestador deve ter 7 dígitos: {p.codigo_municipio!r}"
            )
        if r.opSimpNac not in (1, 2, 3):
            problemas.append(
                f"regime.opSimpNac deve ser 1 (Não Optante), 2 (MEI) ou 3 (ME/EPP); "
                f"recebido {r.opSimpNac!r}"
            )

        # Serviço / códigos de tributação
        if not (s.cTribNac.isdigit() and len(s.cTribNac) == 6):
            problemas.append(
                f"E1235: cTribNac deve ter exatamente 6 dígitos (TSCodTribNac); "
                f"recebido {s.cTribNac!r}"
            )
        if not (s.cTribMun and str(s.cTribMun).strip()):
            problemas.append(
                "E0312: cTribMun é obrigatório (o município administra a combinação "
                "cTribNac+cTribMun; meio-par é rejeitado)"
            )
        if not (s.codigo_municipio_prestacao.isdigit()
                and len(s.codigo_municipio_prestacao) == 7):
            problemas.append(
                f"código IBGE do local da prestação deve ter 7 dígitos: "
                f"{s.codigo_municipio_prestacao!r}"
            )

        # Tributos: Simples (MEI/ME-EPP) exige pTotTribSN (E0712/E1235)
        if r.opSimpNac in (2, 3):
            ptot = s.tributos.get("pTotTribSN")
            if ptot is None or str(ptot).strip() == "":
                problemas.append(
                    f"E0712/E1235: prestador é Simples (opSimpNac={r.opSimpNac}) → "
                    f"'pTotTribSN' é obrigatório em servico.tributos"
                )
            else:
                try:
                    float(str(ptot).replace(",", "."))
                except ValueError:
                    problemas.append(f"servico.tributos.pTotTribSN não é numérico: {ptot!r}")

        # Ambiente
        if self.ambiente not in _AMBIENTES:
            problemas.append(
                f"ambiente inválido: {self.ambiente!r} (use 'homologacao' ou 'producao')"
            )
        return problemas


def validar_tomador(tomador: dict[str, Any] | None) -> list[str]:
    """Valida o bloco do tomador da emissão (E1235 §7). Tomador `None`/sem doc =
    consumidor final (omite <toma>) → sem problemas. Com documento, EXIGE nome e
    documento válido (mód-11)."""
    if not tomador:
        return []
    doc = documentos.digitos(tomador.get("cpf_cnpj") or tomador.get("cpf") or tomador.get("cnpj"))
    if not doc:
        return []  # sem documento → tratado como não identificado (omite <toma>)

    problemas: list[str] = []
    nome = (tomador.get("nome") or tomador.get("xNome") or "").strip()
    if not nome:
        problemas.append(
            "E1235: tomador identificado EXIGE nome (xNome) — a API não resolve pela "
            "Receita (§7); informe o nome ou resolva por CNPJ (BrasilAPI)"
        )
    if len(doc) == 14:
        if not documentos.cnpj_valido(doc):
            problemas.append(f"CNPJ do tomador inválido: {doc!r}")
    elif len(doc) == 11:
        if not documentos.cpf_valido(doc):
            problemas.append(f"CPF do tomador inválido: {doc!r}")
    else:
        problemas.append(
            f"documento do tomador deve ser CPF (11) ou CNPJ (14 dígitos); recebido {doc!r}"
        )
    return problemas
